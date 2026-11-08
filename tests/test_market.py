import market


def test_get_watchlist_snapshot_handles_resolved_and_unresolved_items(monkeypatch):
    monkeypatch.setattr(
        market,
        "_quote_snapshot",
        lambda symbol, base_currency="EUR": {
            "symbol": symbol,
            "price": 101.5,
            "currency": base_currency.upper(),
            "day_change_pct": 1.2,
            "as_of": "2026-11-08T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        market,
        "_forecast_snapshot",
        lambda symbol, base_currency="EUR", horizon_days=30: {
            "symbol": symbol,
            "horizon_days": horizon_days,
            "currency": base_currency.upper(),
            "projected_price": 105.0,
            "expected_return_pct": 3.4,
            "signal": "bullish",
        },
    )

    snapshot = market.get_watchlist_snapshot()
    resolved = next(item for item in snapshot["watchlist"] if item["isin"] == "US0231351067")
    unresolved = next(item for item in snapshot["watchlist"] if item["isin"] == "DE000EWG2LD7")

    assert resolved["status"] == "ok"
    assert resolved["quote"]["price"] == 101.5
    assert resolved["forecast"]["signal"] == "bullish"
    assert unresolved["status"] == "unresolved_ticker"
    assert unresolved["quote"] is None
