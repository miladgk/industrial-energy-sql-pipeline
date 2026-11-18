"""
europe.py
~~~~~~~~~
Finland in Europe: how its wholesale price and the carbon intensity of its
electricity compare with the rest of the continent (Ember data, src/ember.py,
per-country rows from sql/analysis/30).

  - window(): the last twelve months that are complete for Finland in both of
    Ember's files (prices run to the current, unfinished month)
  - ranks(): Finland's place among the countries with complete data
  - spearman(): rank correlation across countries with a permutation p-value.
    With some thirty countries that differ in everything at once (hydro,
    nuclear, interconnection, gas prices), it describes the cross-section; it
    does not say that cutting emissions lowers a country's price.
  - eu_price(): the EU countries' prices weighted by their demand; Ember
    publishes no EU price of its own.
  - price_check(): Ember's monthly price for Finland against the hourly
    ENTSO-E prices in this warehouse (entsoe_price), as a plain mean and
    weighted by consumption. Ember's prices come from ENTSO-E too, so this
    checks the two pipelines agree, not that either is independently right.
"""

from __future__ import annotations

from datetime import date

import numpy as np

FINLAND = "Finland"


def _shift(month: date, k: int) -> date:
    y, m = divmod(month.year * 12 + month.month - 1 + k, 12)
    return date(y, m + 1, 1)


def window(last_generation: date, last_price: date, today: date) -> tuple[date, date]:
    """(first, last) month of the twelve most recent months complete in both files."""
    current = today.replace(day=1)
    last_full_price = last_price if last_price < current else _shift(current, -1)
    end = min(last_generation, last_full_price)
    return _shift(end, -11), end


def ranks(rows: list[dict], area: str = FINLAND) -> dict:
    """Place of *area* among complete countries: 1 = cheapest, cleanest, most wind and solar."""
    c = [r for r in rows if r["complete"]]
    out = {"of": len(c)}
    for key, reverse in (("price_eur_mwh", False), ("intensity_g_kwh", False), ("wind_solar_share", True),
                         ("clean_share", True)):
        order = sorted(c, key=lambda r: r[key], reverse=reverse)
        out[key] = next((i + 1 for i, r in enumerate(order) if r["area"] == area), None)
    return out


def spearman(x, y, n_perm: int = 10000, seed: int = 0) -> dict:
    """Rank correlation and the share of shuffles at least as strong (two-sided)."""
    rx = np.argsort(np.argsort(np.asarray(x, float))).astype(float)
    ry = np.argsort(np.argsort(np.asarray(y, float))).astype(float)
    r = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    perms = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n_perm)])
    return {"r": r, "p_value": float((np.abs(perms) >= abs(r) - 1e-12).mean()), "n": len(rx)}


def correlations(rows: list[dict]) -> dict:
    c = [r for r in rows if r["complete"] and r["area"] != "EU"]
    price = [r["price_eur_mwh"] for r in c]
    return {k: spearman(price, [r[k] for r in c]) for k in ("intensity_g_kwh", "wind_solar_share", "clean_share")}


def eu_price(rows: list[dict]) -> float | None:
    eu = [r for r in rows if r["eu_member"] and r["complete"] and r["demand_twh"]]
    if not eu:
        return None
    w = np.array([r["demand_twh"] for r in eu])
    return float((np.array([r["price_eur_mwh"] for r in eu]) * w).sum() / w.sum())


def price_check(ours: dict, ember: dict) -> dict:
    """ours: {month: (plain mean, consumption-weighted mean)}; ember: {month: price}. Complete months only."""
    months = sorted(set(ours) & set(ember))
    plain = np.array([ours[m][0] - ember[m] for m in months])
    weighted = np.array([ours[m][1] - ember[m] for m in months])
    return {"months": len(months), "first": str(months[0]) if months else None,
            "last": str(months[-1]) if months else None,
            "mean_abs_diff_plain": float(np.abs(plain).mean()) if months else None,
            "max_abs_diff_plain": float(np.abs(plain).max()) if months else None,
            "mean_abs_diff_load_weighted": float(np.abs(weighted).mean()) if months else None}
