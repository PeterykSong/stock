"""공용 기술적 지표 계산 함수 (stock_prices.py, kospi_screener.py 공용)."""

import pandas as pd


def calc_rsi(closes: pd.Series, period: int = 14):
    """Wilder's RSI(period). 데이터가 충분치 않으면 None."""
    closes = closes.dropna()
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    last_avg_gain = avg_gain.iloc[-1]
    last_avg_loss = avg_loss.iloc[-1]
    if pd.isna(last_avg_gain) or pd.isna(last_avg_loss):
        return None
    if last_avg_loss == 0:
        return 100.0
    rs = last_avg_gain / last_avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 2)
