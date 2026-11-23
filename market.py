from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

MIDTERM_HORIZONS = {"6 months": 126, "1 year": 252}

WATCHLIST: list[dict[str, Any]] = [
    {
        "name": "iShares Core MSCI Europe UCITS ETF EUR (Dist)",
        "isin": "IE00B1YZSC51",
        "ticker": "IMEU.AS",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": False,
    },
    {
        "name": "iShares Core MSCI EM IMI UCITS ETF USD (Acc)",
        "isin": "IE00BKM4GZ66",
        "ticker": "EIMI.L",
        "asset_type": "etf",
        "currency": "USD",
        "forecast_enabled": False,
    },
    {
        "name": "EUWAX Gold II",
        "isin": "DE000EWG2LD7",
        "ticker": "EWG2.SG",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": False,
        "midterm_forecast_enabled": True,
    },
    {
        "name": "iShares Core S&P 500 UCITS ETF USD (Acc)",
        "isin": "IE00B5BMR087",
        "ticker": "CSSPX.MI",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "Vanguard FTSE All-World UCITS ETF USD Accumulation",
        "isin": "IE00BK5BQT80",
        "ticker": "VWCE.DE",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "iShares Core S&P 500 UCITS ETF USD Dist",
        "isin": "IE0031442068",
        "ticker": "IUSA.AS",
        "asset_type": "etf",
        "currency": "EUR",
        "forecast_enabled": True,
    },
    {
        "name": "Apple Inc.",
        "isin": "US0231351067",
        "ticker": "AAPL",
        "asset_type": "stock",
        "currency": "USD",
        "forecast_enabled": True,
    },
    {
        "name": "Berkshire Hathaway Inc. Class B",
        "isin": "US0846707026",
        "ticker": "BRK-B",
        "asset_type": "stock",
        "currency": "USD",
        "forecast_enabled": False,
    },
    {
        "name": "ASML Holding N.V.",
        "isin": "USN070592100",
        "ticker": "ASML",
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


def _midterm_forecast_snapshot(
    symbol: str, currency: str
) -> dict[str, Any] | None:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="5y", interval="1d", auto_adjust=True)
    if history.empty:
        return None

    closes = history["Close"].dropna().tolist()
    if len(closes) < 10:
        return None

    x_values = list(range(len(closes)))
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(closes) / len(closes)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return None

    slope = sum(
        (x - x_mean) * (y - y_mean) for x, y in zip(x_values, closes)
    ) / denominator
    intercept = y_mean - (slope * x_mean)
    horizons = {}

    for label, trading_days in MIDTERM_HORIZONS.items():
        projected_price = intercept + (slope * (len(closes) - 1 + trading_days))
        expected_return_pct = (
            ((projected_price / closes[-1]) - 1) * 100 if closes[-1] else 0.0
        )
        horizons[label] = {
            "trading_days": trading_days,
            "currency": currency.upper(),
            "projected_price": round(float(projected_price), 4),
            "expected_return_pct": round(float(expected_return_pct), 4),
            "trend": (
                "upward"
                if expected_return_pct > 0
                else "downward"
                if expected_return_pct < 0
                else "flat"
            ),
        }

    return {
        "method": "linear trend extrapolation",
        "history_period": "5y",
        "horizons": horizons,
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
                    "midterm_forecast": None,
                    "note": "Add the Yahoo Finance ticker to begin live pricing.",
                }
            )
            continue

        try:
            quote = _quote_snapshot(symbol, instrument.get("currency", "EUR"))
            forecast = (
                _forecast_snapshot(symbol, quote["currency"])
                if instrument.get("forecast_enabled")
                else None
            )
            midterm_forecast = (
                _midterm_forecast_snapshot(symbol, quote["currency"])
                if instrument.get("midterm_forecast_enabled")
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
                    "midterm_forecast": midterm_forecast,
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
                    "midterm_forecast": None,
                    "error": str(exc),
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist": items,
    }


def get_quote_snapshot(symbol: str, base_currency: str = "EUR") -> dict[str, Any]:
    return _quote_snapshot(symbol, base_currency)
