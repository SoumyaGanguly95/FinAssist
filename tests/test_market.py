import market
import pandas as pd


def test_midterm_forecast_is_enabled_for_gold_ii_only():
    gold = next(
        instrument
        for instrument in market.WATCHLIST
        if instrument["isin"] == "DE000EWG2LD7"
    )
    other_instruments = [
        instrument
        for instrument in market.WATCHLIST
        if instrument["isin"] != "DE000EWG2LD7"
    ]

    assert gold["midterm_forecast_enabled"] is True
    assert all(not instrument.get("midterm_forecast_enabled") for instrument in other_instruments)


def test_midterm_forecast_extrapolates_6_month_and_1_year_trends(monkeypatch):
    class FakeTicker:
        def history(self, period, interval, auto_adjust):
            assert period == "5y"
            assert interval == "1d"
            assert auto_adjust is True
            return pd.DataFrame(
                {"Close": [100 + 2 * index for index in range(10)]},
                index=pd.date_range("2020-01-01", periods=10),
            )

    monkeypatch.setattr(market.yf, "Ticker", lambda symbol: FakeTicker())

    result = market._midterm_forecast_snapshot("EWG2.SG", "EUR")

    assert result is not None
    assert result["method"] == "linear trend extrapolation"
    assert result["horizons"]["6 months"]["trading_days"] == 126
    assert result["horizons"]["6 months"]["projected_price"] == 370.0
    assert result["horizons"]["1 year"]["trading_days"] == 252
    assert result["horizons"]["1 year"]["projected_price"] == 622.0
    assert result["horizons"]["6 months"]["currency"] == "EUR"


def test_gold_watchlist_attaches_midterm_forecast(monkeypatch):
    monkeypatch.setattr(
        market,
        "WATCHLIST",
        [
            {
                "name": "EUWAX Gold II",
                "isin": "DE000EWG2LD7",
                "ticker": "EWG2.SG",
                "asset_type": "etf",
                "currency": "EUR",
                "forecast_enabled": False,
                "midterm_forecast_enabled": True,
            }
        ],
    )
    monkeypatch.setattr(
        market,
        "_quote_snapshot",
        lambda symbol, base_currency="EUR": {
            "symbol": symbol,
            "price": 100.0,
            "currency": "EUR",
            "day_change_pct": 0.5,
            "as_of": "2026-11-23T00:00:00Z",
        },
    )
    expected_forecast = {"method": "linear trend extrapolation", "horizons": {}}
    monkeypatch.setattr(
        market,
        "_midterm_forecast_snapshot",
        lambda symbol, currency: expected_forecast,
    )

    item = market.get_watchlist_snapshot()["watchlist"][0]

    assert item["forecast"] is None
    assert item["midterm_forecast"] == expected_forecast


def test_get_watchlist_snapshot_handles_resolved_and_unresolved_items(monkeypatch):
    monkeypatch.setattr(
        market,
        "WATCHLIST",
        [
            {
                "name": "Apple Inc.",
                "isin": "US0231351067",
                "ticker": "AAPL",
                "asset_type": "stock",
                "currency": "EUR",
                "forecast_enabled": True,
            },
            {
                "name": "Unresolved fund",
                "isin": "IE0000000000",
                "ticker": None,
                "asset_type": "etf",
                "currency": "EUR",
                "forecast_enabled": True,
            },
        ],
    )
    forecast_currencies = []
    monkeypatch.setattr(
        market,
        "_quote_snapshot",
        lambda symbol, base_currency="EUR": {
            "symbol": symbol,
            "price": 101.5,
            "currency": "USD",
            "day_change_pct": 1.2,
            "as_of": "2026-11-08T00:00:00Z",
        },
    )

    def fake_forecast_snapshot(symbol, base_currency="EUR", horizon_days=30):
        forecast_currencies.append(base_currency)
        return {
            "symbol": symbol,
            "horizon_days": horizon_days,
            "currency": base_currency.upper(),
            "projected_price": 105.0,
            "expected_return_pct": 3.4,
            "signal": "bullish",
        }

    monkeypatch.setattr(market, "_forecast_snapshot", fake_forecast_snapshot)

    snapshot = market.get_watchlist_snapshot()
    resolved = next(item for item in snapshot["watchlist"] if item["isin"] == "US0231351067")
    unresolved = next(item for item in snapshot["watchlist"] if item["isin"] == "IE0000000000")

    assert resolved["status"] == "ok"
    assert resolved["quote"]["price"] == 101.5
    assert resolved["forecast"]["signal"] == "bullish"
    assert forecast_currencies == ["USD"]
    assert unresolved["status"] == "unresolved_ticker"
    assert unresolved["quote"] is None
