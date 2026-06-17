#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOSPI Screener (현재가 + MA20 + PBR/ROE)
---------------------------------------
기존 kospi_ma_screener_now.py 흐름을 유지하면서 다음을 추가:
  1) PBR 추가
  2) ROE(= EPS / BPS * 100) 계산 추가
  3) Momentum(= 0.6 * Price/MA5 + 0.4 * MA5/MA20) 계산 추가
  4) Score(매수 매력도) = ROE와 Momentum을 각각 0~1로 정규화한 뒤 50:50 가중 합산
  5) 결과를 Score 내림차순으로 정렬

요구 패키지:
    pip install finance-datareader pandas tqdm requests pykrx

사용 예:
    python3 kospi_screener.py --start 2026-01-01 --exclude-etf --min-days 30
"""

import argparse
import datetime as dt
import sys
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

try:
    import FinanceDataReader as fdr
except ImportError:
    print(
        "FinanceDataReader가 필요합니다. 먼저 아래를 실행하세요:\n"
        "  pip install finance-datareader pandas tqdm requests pykrx",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from pykrx import stock
except ImportError:
    print(
        "pykrx가 필요합니다. 먼저 아래를 실행하세요:\n"
        "  pip install pykrx",
        file=sys.stderr,
    )
    sys.exit(1)


def guess_default_start(days_back: int = 180) -> str:
    return (dt.date.today() - dt.timedelta(days=days_back)).strftime("%Y-%m-%d")


def latest_business_day(lookback_days: int = 10) -> str:
    """가장 최근 영업일(YYYYMMDD)을 KRX OHLCV 응답으로 추정"""
    cursor = dt.date.today()
    for _ in range(lookback_days):
        ymd = cursor.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(ymd, ymd, "005930")
            if not df.empty:
                return ymd
        except Exception:
            pass
        cursor -= dt.timedelta(days=1)
    return dt.date.today().strftime("%Y%m%d")


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

    return lst.reset_index(drop=True)[["Symbol", "Name"]]


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
    """가격 DF에서 MA5/MA20 계산 후 마지막 값 Series 반환"""
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
            "Close": float(last["Close"]),
            "MA5": float(last["MA5"]),
            "MA20": float(last["MA20"]),
        }
    )


def fetch_symbol_prices(symbol: str, start: str) -> pd.DataFrame:
    df = fdr.DataReader(symbol, start)
    return normalize_close_column(df)


def fetch_current_price(symbol: str, start: str) -> Optional[float]:
    """최신 조회 데이터의 마지막 Close를 현재 비교 가격으로 사용"""
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


def load_fundamentals() -> pd.DataFrame:
    """당일 기준 KOSPI 전종목 기본지표 로드"""
    business_day = latest_business_day()
    df = stock.get_market_fundamental_by_ticker(business_day, market="KOSPI")
    if df.empty:
        raise RuntimeError(f"KOSPI 기본지표를 불러오지 못했습니다. 기준일: {business_day}")

    df = df.reset_index()
    if "티커" in df.columns:
        df = df.rename(columns={"티커": "Symbol"})
    else:
        first_col = df.columns[0]
        df = df.rename(columns={first_col: "Symbol"})
    df["Symbol"] = df["Symbol"].astype(str).str.zfill(6)

    numeric_cols = ["BPS", "PER", "PBR", "EPS", "DIV", "DPS"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in numeric_cols:
        if col not in df.columns:
            df[col] = pd.NA

    bps = pd.to_numeric(df["BPS"], errors="coerce").where(pd.to_numeric(df["BPS"], errors="coerce") != 0)
    eps = pd.to_numeric(df["EPS"], errors="coerce")
    df["ROE"] = (eps / bps) * 100.0
    return df[["Symbol", "BPS", "PER", "PBR", "EPS", "DIV", "DPS", "ROE"]]


def minmax_normalize(series: pd.Series) -> pd.Series:
    """0~1로 정규화 (값이 클수록 1에 가까움, 방향 보존). 전 종목 값이 같으면 0.5로 처리."""
    s_min = series.min()
    s_max = series.max()
    if pd.isna(s_min) or pd.isna(s_max) or s_max == s_min:
        return series.where(series.isna(), 0.5)
    return (series - s_min) / (s_max - s_min)


def screen_kospi(
    start: str,
    exclude_etf: bool = True,
    min_days: int = 30,
    quiet: bool = False,
    price_max_multiple: float = 1.05,
    require_below: bool = True,
) -> pd.DataFrame:
    """KOSPI 전체 스크리닝 후 PBR/ROE를 결합"""
    kospi = load_kospi_list(exclude_etf=exclude_etf)
    fundamentals = load_fundamentals()
    fundamentals_map = fundamentals.set_index("Symbol")

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
            if not (cond_below and cond_band):
                continue

            ma5 = ma["MA5"]
            price_over_ma5 = price_now / ma5 if ma5 != 0 else None
            ma5_over_ma20 = ma5 / ma20 if ma20 != 0 else None
            momentum = (
                0.6 * price_over_ma5 + 0.4 * ma5_over_ma20
                if price_over_ma5 is not None and ma5_over_ma20 is not None
                else None
            )

            fundamental = fundamentals_map.loc[symbol] if symbol in fundamentals_map.index else None
            rows.append(
                {
                    "Symbol": symbol,
                    "Name": name,
                    "Date": ma["Date"],
                    "Price": price_now,
                    "Close": ma["Close"],
                    "MA5": ma5,
                    "MA20": ma20,
                    "Price/MA20": price_now / ma20 if ma20 != 0 else None,
                    "Price/MA5": price_over_ma5,
                    "Momentum": momentum,
                    "PBR": fundamental["PBR"] if fundamental is not None else None,
                    "ROE": fundamental["ROE"] if fundamental is not None else None,
                    "PER": fundamental["PER"] if fundamental is not None else None,
                    "EPS": fundamental["EPS"] if fundamental is not None else None,
                    "BPS": fundamental["BPS"] if fundamental is not None else None,
                    "DIV": fundamental["DIV"] if fundamental is not None else None,
                    "DPS": fundamental["DPS"] if fundamental is not None else None,
                }
            )
        except Exception as e:
            if not quiet:
                print(f"[WARN] {symbol}({name}) 처리 중 오류: {e}", file=sys.stderr)
            continue

    columns = [
        "Symbol", "Name", "Date", "Price", "Close", "MA5", "MA20", "Price/MA20", "Price/MA5",
        "PBR", "ROE", "PER", "EPS", "BPS", "DIV", "DPS", "Momentum", "Score",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)

    result = pd.DataFrame(rows)

    norm_roe = minmax_normalize(result["ROE"])
    norm_momentum = minmax_normalize(result["Momentum"])
    result["Score"] = 0.5 * norm_roe + 0.5 * norm_momentum

    result = result.sort_values(
        by=["Score", "ROE", "PBR", "Symbol"],
        ascending=[False, False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    return result[columns]


def main():
    parser = argparse.ArgumentParser(
        description="KOSPI 스크리너 (현재가 + MA20 + PBR/ROE, ROE 내림차순 정렬)"
    )
    parser.add_argument("--start", type=str, default=None, help="데이터 조회 시작일 (YYYY-MM-DD). 미지정 시 최근 180일.")
    parser.add_argument("--exclude-etf", action="store_true", help="ETF/ETN/리츠/스팩/우선주 추정 종목 제외")
    parser.add_argument("--min-days", type=int, default=30, help="최소 유효 데이터 일수(rolling NaN 방지)")
    parser.add_argument("--quiet", action="store_true", help="진행 출력 최소화")
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

    fname = "kospi_screener.csv"
    df.to_csv(fname, index=False, encoding="utf-8-sig")
    print(f"\nCSV 저장 완료: {fname}")


if __name__ == "__main__":
    main()
