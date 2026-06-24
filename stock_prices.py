"""
주식 가격 조회 스크립트 (로컬 / GitHub Actions 공용)
- 한국 종목: pykrx 로 KRX 최근 영업일 종가 조회
- 미국 종목: yfinance 로 조회

설치:
    pip install -r requirements.txt
    (또는: pip install pykrx yfinance pandas)

실행:
    python stock_prices.py

출력:
    - 콘솔 표
    - stock_prices_result.csv
    - stock_prices_result.md   (브리핑용 마크다운)
"""

from datetime import datetime, timedelta, timezone
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from pykrx import stock
import yfinance as yf


# ── 종목 정의 ────────────────────────────────────────────────
KR_TICKERS = {
    "삼성전자":   "005930",
    "SK하이닉스": "000660",
    "한화오션":   "042660",
    "효성중공업": "298040",
}

# 주의: "TLSA"는 Tiziana Life Sciences(바이오 소형주)입니다.
#       테슬라가 필요하면 "TSLA"로 바꾸세요.
US_TICKERS = ["NVDA", "AMD", "NVDY", "AMDY", "GOOY", "TSLA","MSFT"]

KST = timezone(timedelta(hours=9))


def latest_business_day():
    """가장 최근 영업일(YYYYMMDD)을 KRX 기준으로 추정."""
    d = datetime.now(KST)
    for _ in range(10):
        ymd = d.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(ymd, ymd, "005930")
            if not df.empty:
                return ymd
        except Exception:
            pass
        d -= timedelta(days=1)
    return datetime.now(KST).strftime("%Y%m%d")


def get_kr_prices():
    rows = []
    day = latest_business_day()
    for name, code in KR_TICKERS.items():
        try:
            df = stock.get_market_ohlcv(day, day, code)
            close = int(df["종가"].iloc[-1]) if not df.empty else None
            chg = round(float(df["등락률"].iloc[-1]),2) if not df.empty else None
        except Exception as e:
            close, chg = None, None
            print(f"[KR] {name}({code}) 조회 실패: {e}")
        rows.append({
            "종목": name, "티커": code, "시장": "KRX",
            "종가": close, "등락률(%)": chg, "통화": "KRW", "기준일": day,
        })
    return rows


def get_us_prices():
    rows = []
    for sym in US_TICKERS:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if hist.empty:
                raise ValueError("no data")
            close = round(float(hist["Close"].iloc[-1]), 2)
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else close
            chg = round((close - prev) / prev * 100, 2) if prev else None
            day = hist.index[-1].strftime("%Y%m%d")
        except Exception as e:
            close, chg, day = None, None, None
            print(f"[US] {sym} 조회 실패: {e}")
        rows.append({
            "종목": sym, "티커": sym, "시장": "US",
            "종가": close, "등락률(%)": chg, "통화": "USD", "기준일": day,
        })
    return rows


def main():
    data = get_kr_prices() + get_us_prices()
    df = pd.DataFrame(data, columns=["종목", "티커", "시장", "종가", "등락률(%)", "통화", "기준일"])

    pd.set_option("display.unicode.east_asian_width", True)
    print("\n=== 주가 조회 결과 ===")
    print(df.to_string(index=False))

    df.to_csv("stock_prices_result.csv", index=False, encoding="utf-8-sig")

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    with open("stock_prices_result.md", "w", encoding="utf-8") as f:
        f.write(f"# 주가 브리핑 ({now})\n\n")
        f.write("| 종목 | 티커 | 종가 | 등락률(%) | 통화 | 기준일 |\n")
        f.write("|---|---|---:|---:|---|---|\n")
        for r in data:
            price = f"{r['종가']:,}" if r["종가"] is not None else "N/A"
            chg = r["등락률(%)"] if r["등락률(%)"] is not None else "N/A"
            f.write(f"| {r['종목']} | {r['티커']} | {price} | {chg} | {r['통화']} | {r['기준일']} |\n")

    print("\n저장 완료: stock_prices_result.csv, stock_prices_result.md")


if __name__ == "__main__":
    main()
