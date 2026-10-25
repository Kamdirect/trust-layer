"""An independent test generator, written after the checks were finished, to test generalisation.

The development data (src/synthetic_data.py) always has the same 4 regions, 6 products,
the same seasonality and noise, and the same 6 problems at the same sizes. The checks were
built and tuned on it. This generator differs on purpose:

  - Business shape: 3-6 regions, 5-9 products with random prices and volumes, random
    seasonal strength and peak month, and random noise.
  - Harmless differences: finance books small credit notes and price corrections (up to
    0.3% of a row's revenue) on about 15% of rows. These are NOT problems, and a good tool
    should not send an analyst to chase them.
  - Problems: each type appears in a case with probability 0.6, at a random place, at a
    random size, including sizes and labels the checks were never tuned on:
      subtotal row      labels "Total", "TOTAL", "Sub-total", "Region total", "" or "All products"
      duplicate rows    1-4 rows
      missing period    one region-month absent from the extract
      blank value       one volume or revenue cell left empty (a type never planted in development)
      finance gap       an unexplained adjustment of GBP 500-5,000, either direction
      unit mix-up       packs of 6, 12 or 24 entered as cases
      wrong value       x2, x3, x5, x10, or x0.1 (a dropped zero)
  - Where the error is: extract problems are in File A only. A unit mix-up or wrong value is
    entered in the SOURCE system half the time, so it appears in BOTH files and comparing
    the files cannot see it.
  - 20% of cases contain no problems at all, to measure false alarms.

Each planted problem sits in its own region-month, so one flag cannot be credited twice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNS = ["month", "region", "product", "unit", "volume", "revenue_gbp"]
REGION_NAMES = ["Scotland", "North West", "North East", "Midlands", "Wales", "London",
                "South East", "South West"]
PRODUCT_NAMES = ["Cola 330ml", "Cola 2L", "Zero Cola 500ml", "Lemonade 1.5L", "Ginger Beer 330ml",
                 "Apple Juice 1L", "Smoothie 250ml", "Iced Tea 500ml", "Sparkling Water 1L",
                 "Sports Drink 750ml", "Energy Zero 250ml", "Tonic 200ml"]
SUBTOTAL_LABELS = ["Total", "TOTAL", "Sub-total", "Region total", "", "All products"]
VALUE_FACTORS = [2, 3, 5, 10, 0.1]
PACK_SIZES = [6, 12, 24]
TYPES = ["subtotal_row", "duplicate_row", "missing_period", "missing_value",
         "reconciliation_gap", "unit_mismatch", "outlier"]


def _truth(rng: np.random.Generator) -> pd.DataFrame:
    regions = list(rng.choice(REGION_NAMES, size=int(rng.integers(3, 7)), replace=False))
    products = list(rng.choice(PRODUCT_NAMES, size=int(rng.integers(5, 10)), replace=False))
    price = {p: float(rng.uniform(3, 25)) for p in products}
    base = {p: float(rng.uniform(200, 2000)) for p in products}
    scale = {r: float(rng.uniform(0.6, 1.5)) for r in regions}
    amplitude, peak, noise = rng.uniform(0.1, 0.45), rng.uniform(6, 8), rng.uniform(0.05, 0.12)
    rows = []
    for m in range(1, 13):
        season = 1 + amplitude * np.cos((m - peak) / 12 * 2 * np.pi)
        for r in regions:
            for p in products:
                v = int(round(base[p] * scale[r] * season * rng.lognormal(0, noise)))
                unit_price = price[p] * rng.normal(1, rng.uniform(0.01, 0.03))
                rows.append({"month": f"2025-{m:02d}", "region": r, "product": p, "unit": "cases",
                             "volume": v, "revenue_gbp": round(v * unit_price, 2)})
    return pd.DataFrame(rows, columns=COLUMNS)


def _harmless_finance_differences(b: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    b = b.copy()
    touched = rng.random(len(b)) < 0.15
    b.loc[touched, "revenue_gbp"] = (b.loc[touched, "revenue_gbp"]
                                     * (1 + rng.uniform(-0.003, 0.003, touched.sum()))).round(2)
    return b


def make_case(seed: int, clean: bool | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Return (file_a, file_b, answer_key). clean=None: 20% chance of a case with no problems."""
    rng = np.random.default_rng(seed)
    truth = _truth(rng)
    if clean is None:
        clean = rng.random() < 0.2
    a, b = truth.copy(), _harmless_finance_differences(truth, rng)
    if clean:
        return a, b, []

    chosen = [t for t in TYPES if rng.random() < 0.6] or [TYPES[int(rng.integers(len(TYPES)))]]
    cells = list(truth[["month", "region"]].drop_duplicates().itertuples(index=False, name=None))
    order = rng.permutation(len(cells))
    places = {t: cells[order[i]] for i, t in enumerate(chosen)}  # one region-month per problem
    key, subtotals, duplicates, drop_cell = [], [], [], None

    def rows_at(df, month, region, product=None):
        m = (df["month"] == month) & (df["region"] == region)
        return m & (df["product"] == product) if product is not None else m

    for t in chosen:
        month, region = places[t]
        products = truth.loc[rows_at(truth, month, region), "product"].tolist()
        product = products[int(rng.integers(len(products)))]
        entry = {"issue_type": t, "detail": {}}
        if t == "subtotal_row":
            block = truth[rows_at(truth, month, region)]
            label = SUBTOTAL_LABELS[int(rng.integers(len(SUBTOTAL_LABELS)))]
            subtotals.append({"month": month, "region": region, "product": label, "unit": "cases",
                              "volume": int(block["volume"].sum()),
                              "revenue_gbp": round(float(block["revenue_gbp"].sum()), 2)})
            entry.update(file="A", rows=[{"month": month, "region": region, "product": label or None}],
                         detail={"label": label})
        elif t == "duplicate_row":
            k = int(rng.integers(1, 5))
            dup = a[rows_at(a, month, region)].sample(k, random_state=int(rng.integers(1 << 31)))
            duplicates.append(dup)
            entry.update(file="A", rows=[{"month": month, "region": region, "product": p}
                                         for p in dup["product"]], detail={"rows": k})
        elif t == "missing_period":
            drop_cell = (month, region)
            entry.update(file="A", rows=[{"month": month, "region": region, "product": None}])
        elif t == "missing_value":
            col = "volume" if rng.random() < 0.5 else "revenue_gbp"
            a.loc[rows_at(a, month, region, product), col] = np.nan
            entry.update(file="A", rows=[{"month": month, "region": region, "product": product}],
                         detail={"column": col})
        elif t == "reconciliation_gap":
            amount = round(float(rng.uniform(500, 5000)) * (1 if rng.random() < 0.5 else -1), 2)
            mask = rows_at(b, month, region, product)
            b.loc[mask, "revenue_gbp"] = (b.loc[mask, "revenue_gbp"] - amount).round(2)
            entry.update(file="B", rows=[{"month": month, "region": region, "product": product}],
                         detail={"amount_gbp": amount})
        elif t in ("unit_mismatch", "outlier"):
            both = rng.random() < 0.5
            targets = [a, b] if both else [a]
            if t == "unit_mismatch":
                factor = int(PACK_SIZES[int(rng.integers(len(PACK_SIZES)))])
                for df in targets:
                    df.loc[rows_at(df, month, region, product), "volume"] *= factor
            else:
                factor = float(VALUE_FACTORS[int(rng.integers(len(VALUE_FACTORS)))])
                for df in targets:
                    m = rows_at(df, month, region, product)
                    df.loc[m, "volume"] = (df.loc[m, "volume"] * factor).round()
                    df.loc[m, "revenue_gbp"] = (df.loc[m, "revenue_gbp"] * factor).round(2)
            entry.update(file="A and B" if both else "A",
                         rows=[{"month": month, "region": region, "product": product}],
                         detail={"factor": factor, "in_both_files": both})
        key.append(entry)

    if drop_cell:
        a = a[~rows_at(a, *drop_cell)]
    parts = [a]
    if subtotals:
        parts.append(pd.DataFrame(subtotals, columns=COLUMNS))
    parts += duplicates
    a = pd.concat(parts, ignore_index=True)
    return a, b.reset_index(drop=True), key
