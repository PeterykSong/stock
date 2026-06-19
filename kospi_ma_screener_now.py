#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOSPI MA Screener (현재가 기준 비교 버전)
---------------------------------------
조건 (기본):
  1) 현재가 < 20일선(MA20)                [--require-below 로 제어, 기본 True]
  2) 현재가 <= (price_max_multiple * MA20)  [--price-max-multiple, 기본 1.05]

※ MA5/MA20 계산은 종가(Close) 기준으로 유지
※ 비교 기준만 종가가 아니라 '현재가'로 변경

요구 패키지:
    pip install finance-datareader pandas tqdm requests

사용 예:
    python kospi_ma_screener_now.py --start 2026-01-01 --exclude-etf --min-days 30 --save --price-max-multiple 1.05
    python kospi_ma_screener_now.py --start 2026-01-01 --exclude-etf --min-days 30 --save --price-max-multiple 0.95

옵션:
    --start YYYY-MM-DD
    --exclude-etf
    --min-days N
    --quiet
    --save
    --show-top N
    --price-max-multiple FLOAT   (기본 1.05)
    --no-require-below           (기본은 require-below=True; 이 플래그를 쓰면 False가 됨)
"""

import argparse
import datetime as dt
import sys
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from tqdm import tqdm

try:
    import FinanceDataReader as fdr
except ImportError:
    print(
        "FinanceDataReader가 필요합니다. 먼저 아래를 실행하세요:\n"
        "  pip install finance-datareader pandas tqdm requests",
        file=sys.stderr,
    )
    sys.exit(1)


def guess_default_start(days_back: int = 180) -> str:
    return (dt.date.today() - dt.timedelta(days=days_back)).strftime("%Y-%m-%d")


EXCLUDE_KEYWORDS = [
    "ETF", "ETN", "REIT", "리츠", "스팩", "SPAC", "우", "우B", "우선주"
]


def load_kospi_list(exclude_etf: bool = True) -> pd.DataFrame:
    """KOSPI 상장 목록 로드 (KIND 다운로드 + 한글 인코딩 처리)"""
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&marketType=stockMkt"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"KOSPI 종목 목록 HTTP 요청 실패: {e}")

    text = None
    for enc in ("cp949", "euc-kr", "utf-8"):
        try:
            text = resp.content.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise RuntimeError("KOSPI 종목 목록 디코딩 실패 (cp949/euc-kr/utf-8 모두 실패)")

    try:
        tables = pd.read_html(StringIO(text), header=0)
    except Exception as e:
        raise RuntimeError(f"KOSPI 종목 목록 테이블 파싱 실패: {e}")

    if not tables:
        raise RuntimeError("KOSPI 종목 목록 테이블을 찾지 못했습니다.")

    lst = tables[0].copy()

    if "종목코드" not in lst.columns or "회사명" not in lst.columns:
        raise KeyError(f"예상한 컬럼이 없습니다. 현재 컬럼: {list(lst.columns)}")

    lst = lst.rename(columns={"종목코드": "Symbol", "회사명": "Name"})
    lst["Symbol"] = lst["Symbol"].astype(str).str.zfill(6)
    lst = lst.drop_duplicates(subset=["Symbol"])

    if exclude_etf:
        pat = "|".join(EXCLUDE_KEYWORDS)
        mask = ~lst["Name"].str.contains(pat, case=False, na=False)
        lst = lst[mask]

    lst = lst.reset_index(drop=True)
    return lst[["Symbol", "Name"]]


def normalize_close_column(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DF의 종가 컬럼명을 Close로 표준화"""
    out = df.copy()
    if "Close" not in out.columns:
        for cand in ["close", "Adj Close"]:
            if cand in out.columns:
                out = out.rename(columns={cand: "Close"})
                break
    if "Close" not in out.columns:
        raise ValueError("가격 데이터프레임에 'Close' 컬럼이 없습니다.")
    return out


def compute_ma_row(df_price: pd.DataFrame, current_price: Optional[float] = None) -> pd.Series:
    """가격 DF에서 MA5/MA20 계산 후 마지막 값 Series 반환
    - MA는 종가 기준
    - Price는 current_price가 있으면 현재가, 없으면 마지막 종가
    """
    df = normalize_close_column(df_price)

    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df = df.dropna(subset=["MA5", "MA20"])
    if df.empty:
        return pd.Series(dtype="float64")

    last = df.iloc[-1]
    price_for_compare = float(current_price) if current_price is not None else float(last["Close"])

    return pd.Series(
        {
            "Date": last.name.strftime("%Y-%m-%d") if hasattr(last.name, "strftime") else str(last.name),
            "Price": price_for_compare,
            "Close": float(last["Close"]),   # 참고용 종가
            "MA5": float(last["MA5"]),
            "MA20": float(last["MA20"]),
        }
    )


def fetch_symbol_prices(symbol: str, start: str) -> pd.DataFrame:
    """심볼별 일별 가격 데이터 로드 (KRX 심볼 6자리)"""
    df = fdr.DataReader(symbol, start)
    return normalize_close_column(df)


def fetch_current_price(symbol: str, start: str) -> Optional[float]:
    """현재가 조회
    FinanceDataReader만으로는 실시간 체결가를 직접 안정적으로 주지 않는 경우가 많아서,
    우선 '최신 조회 데이터의 마지막 Close'를 현재 비교 가격으로 사용.
    장중이면 데이터 소스에 따라 당일 가격으로 반영될 수 있음.
    """
    try:
        recent_start = (dt.date.today() - dt.timedelta(days=10)).strftime("%Y-%m-%d")
        effective_start = max(start, recent_start)
        df = fdr.DataReader(symbol, effective_start)
        df = normalize_close_column(df)
        if df.empty:
            return None
        return float(df.iloc[-1]["Close"])
    except Exception:
        return None


def screen_kospi(
    start: str,
    exclude_etf: bool = True,
    min_days: int = 30,
    quiet: bool = False,
    price_max_multiple: float = 1.05,
    require_below: bool = True,
) -> pd.DataFrame:
    """KOSPI 전체 스크리닝.
    조건: (require_below -> 현재가 < MA20) AND (현재가 <= price_max_multiple * MA20)
    """
    kospi = load_kospi_list(exclude_etf=exclude_etf)

    rows = []
    iterator = kospi.itertuples(index=False)
    if not quiet:
        iterator = tqdm(iterator, total=len(kospi), desc="스크리닝 진행 중")

    for row in iterator:
        symbol, name = row.Symbol, row.Name
        try:
            price_df = fetch_symbol_prices(symbol, start)
            if price_df is None or price_df.empty or len(price_df) < min_days:
                continue

            current_price = fetch_current_price(symbol, start)
            ma = compute_ma_row(price_df, current_price=current_price)
            if ma.empty:
                continue

            price_now = ma["Price"]
            ma20 = ma["MA20"]

            cond_band = price_now <= (price_max_multiple * ma20)
            cond_below = (price_now < ma20) if require_below else True

            if cond_below and cond_band:
                rows.append(
                    {
                        "Symbol": symbol,
                        "Name": name,
                        "Date": ma["Date"],
                        "Price": price_now,          # 현재 비교 가격
                        "Close": ma["Close"],        # 마지막 종가 참고용
                        "MA5": ma["MA5"],
                        "MA20": ma20,
                        "Price/MA20": price_now / ma20 if ma20 != 0 else None,
                    }
                )
        except Exception as e:
            if not quiet:
                print(f"[WARN] {symbol}({name}) 처리 중 오류: {e}", file=sys.stderr)
            continue

    if rows:
        result = pd.DataFrame(rows).sort_values(["Date", "Symbol"]).reset_index(drop=True)
    else:
        result = pd.DataFrame(columns=["Symbol", "Name", "Date", "Price", "Close", "MA5", "MA20", "Price/MA20"])

    return result


def main():
    parser = argparse.ArgumentParser(
        description="KOSPI MA 스크리너 (현재가 기준 조건: Price < MA20, Price <= k*MA20)"
    )
    parser.add_argument("--start", type=str, default=None, help="데이터 조회 시작일 (YYYY-MM-DD). 미지정 시 최근 180일.")
    parser.add_argument("--exclude-etf", action="store_true", help="ETF/ETN/리츠/스팩/우선주 추정 종목 제외")
    parser.add_argument("--min-days", type=int, default=30, help="최소 유효 데이터 일수(rolling NaN 방지)")
    parser.add_argument("--quiet", action="store_true", help="진행 출력 최소화")
    parser.add_argument("--save", action="store_true", help="CSV 저장 (파일명 자동 생성)")
    parser.add_argument("--show-top", type=int, default=30, help="화면에 미리보기로 보여줄 행 수")
    parser.add_argument(
        "--price-max-multiple",
        type=float,
        default=1.05,
        help="현재가 <= (이 값 * MA20) 조건의 배수값. 예: 1.05, 0.95 등",
    )
    parser.add_argument("--no-require-below", action="store_true", help="기본 현재가 < MA20 조건 비활성화")
    args = parser.parse_args()

    start = args.start or guess_default_start(180)
    df = screen_kospi(
        start=start,
        exclude_etf=args.exclude_etf,
        min_days=args.min_days,
        quiet=args.quiet,
        price_max_multiple=args.price_max_multiple,
        require_below=not args.no_require_below,
    )

    if df.empty:
        print("조건에 맞는 종목이 없습니다.")
    else:
        print(df.head(args.show_top).to_string(index=False))

    if args.save and not df.empty:
        today = dt.date.today().strftime("%Y%m%d")
        fname = f"kospi_price_vs_ma20_{today}.csv"
        df.to_csv(fname, index=False, encoding="utf-8-sig")
        print(f"\nCSV 저장 완료: {fname}")


if __name__ == "__main__":
    main()
