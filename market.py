from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

WATCHLIST: list[dict[str, Any]] = [
    {
        "name": "VWCE",
        "isin": "IE00B1YZSC51",
        "ticker": "VWCE.L",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": False,
    },
    {
        "name": "VUSA",
        "isin": "IE00BKM4GZ66",
        "ticker": "VUSA.L",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": False,
    },
    {
        "name": "DE000EWG2LD7",
        "isin": "DE000EWG2LD7",
        "ticker": None,
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": False,
    },
    {
        "name": "IE00B5BMR087",
        "isin": "IE00B5BMR087",
        "ticker": None,
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "IE00BK5BQT80",
        "isin": "IE00BK5BQT80",
        "ticker": None,
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "IE0031442068",
        "isin": "IE0031442068",
        "ticker": None,
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "AAPL",
        "isin": "US0231351067",
        "ticker": "AAPL",
        "asset_type": "stock",
        "currency": "USD",
        "forecast_enabled": True,
    },
    {
        "name": "US0846707026",
        "isin": "US0846707026",
        "ticker": None,
        "asset_type": "stock",
        "currency": "USD",
        "forecast_enabled": False,
    },
    {
        "name": "USN070592100",
        "isin": "USN070592100",
        "ticker": None,
        "asset_type": "stock",
        "currency": "USD",
        "forecast_enabled": True,
    },
]


def _quote_snapshot(symbol: str, base_currency: str = "EUR") -> dict[str, Any]:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="5d", interval="1d", auto_adjust=True)
    if history.empty:
        raise ValueError(f"No recent market data found for {symbol}")

    closes = history["Close"].dropna()
    last_price = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2]) if len(closes) > 1 else last_price
    delta_pct = 0.0 if previous_close == 0 else ((last_price - previous_close) / previous_close) * 100

    info = getattr(ticker, "fast_info", {}) or {}
    currency = (info.get("currency") or base_currency or "EUR").upper()

    return {
        "symbol": symbol,
        "price": round(last_price, 4),
        "previous_close": round(previous_close, 4),
        "currency": currency,
        "day_change_pct": round(delta_pct, 4),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _forecast_snapshot(symbol: str, base_currency: str = "EUR", horizon_days: int = 30) -> dict[str, Any] | None:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="180d", interval="1d", auto_adjust=True)
    if history.empty or len(history["Close"].dropna()) < 10:
        return None

    closes = history["Close"].dropna().tolist()
    x_values = list(range(len(closes)))
    y_values = closes
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return None

    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / denominator
    intercept = y_mean - (slope * x_mean)

    future_index = len(x_values) + horizon_days
    expected_price = intercept + (slope * future_index)
    expected_return_pct = ((expected_price / closes[-1]) - 1) * 100 if closes[-1] else 0.0

    return {
        "symbol": symbol,
        "horizon_days": horizon_days,
        "currency": base_currency.upper(),
        "projected_price": round(float(expected_price), 4),
        "expected_return_pct": round(float(expected_return_pct), 4),
        "signal": "bullish" if expected_return_pct > 0 else "bearish" if expected_return_pct < 0 else "neutral",
    }


def get_watchlist_snapshot() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for instrument in WATCHLIST:
        symbol = instrument.get("ticker")
        if not symbol:
            items.append(
                {
                    "name": instrument.get("name"),
                    "isin": instrument.get("isin"),
                    "asset_type": instrument.get("asset_type"),
                    "status": "unresolved_ticker",
                    "quote": None,
                    "forecast": None,
                    "note": "Add the Yahoo Finance ticker to begin live pricing.",
                }
            )
            continue

        try:
            quote = _quote_snapshot(symbol, instrument.get("currency", "EUR"))
            forecast = (
                _forecast_snapshot(symbol, instrument.get("currency", "EUR"))
                if instrument.get("forecast_enabled")
                else None
            )
            items.append(
                {
                    "name": instrument.get("name"),
                    "isin": instrument.get("isin"),
                    "ticker": symbol,
                    "asset_type": instrument.get("asset_type"),
                    "currency": quote["currency"],
                    "status": "ok",
                    "quote": quote,
                    "forecast": forecast,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive path, exercised by integration tests
            items.append(
                {
                    "name": instrument.get("name"),
                    "isin": instrument.get("isin"),
                    "ticker": symbol,
                    "asset_type": instrument.get("asset_type"),
                    "status": "error",
                    "quote": None,
                    "forecast": None,
                    "error": str(exc),
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist": items,
    }


def get_quote_snapshot(symbol: str, base_currency: str = "EUR") -> dict[str, Any]:
    return _quote_snapshot(symbol, base_currency)
