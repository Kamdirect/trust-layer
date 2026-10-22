"""Generate synthetic sales data with known, deliberately planted problems.

Two files are produced:
  - sales_system.csv  : "File A", an extract from a (fictional) sales system.
                        Five of the six planted problems live here.
  - finance_report.csv: "File B", the finance team's version of the same numbers.
                        Clean, except for one planted manual adjustment.
  - answer_key.json   : the list of every planted problem. Used to score the checks.

All data is synthetic. No real company data is used.
Run from the project root:  python -m src.synthetic_data
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
YEAR = 2025
REGIONS = ["North", "South", "East", "West"]

# Product -> (price per case in GBP, base monthly volume in cases)
PRODUCTS = {
    "Cola 500ml": (9.60, 1200),
    "Diet Cola 500ml": (9.60, 800),
    "Lemon Soda 330ml": (7.20, 600),
    "Orange Juice 1L": (14.40, 400),
    "Still Water 1.5L": (4.80, 1500),
    "Energy Drink 250ml": (18.00, 300),
}
REGION_SCALE = {"North": 1.0, "South": 1.3, "East": 0.8, "West": 1.1}
BOTTLES_PER_CASE = 24

COLUMNS = ["month", "region", "product", "unit", "volume", "revenue_gbp"]


def _seasonality(month: int) -> float:
    """Drinks peak in summer: about +30% in July, about -30% in January."""
    return 1.0 + 0.3 * np.sin((month - 4) / 12 * 2 * np.pi)


def generate_clean(seed: int = SEED) -> pd.DataFrame:
    """Return the 'true' monthly sales table: 12 months x 4 regions x 6 products."""
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(1, 13):
        for region in REGIONS:
            for product, (price, base) in PRODUCTS.items():
                volume = base * REGION_SCALE[region] * _seasonality(m)
                volume = int(round(volume * rng.normal(1.0, 0.08)))
                unit_price = price * rng.normal(1.0, 0.02)  # small promo/mix noise
                rows.append(
                    {
                        "month": f"{YEAR}-{m:02d}",
                        "region": region,
                        "product": product,
                        "unit": "cases",
                        "volume": volume,
                        "revenue_gbp": round(volume * unit_price, 2),
                    }
                )
    return pd.DataFrame(rows, columns=COLUMNS)


def _key(row: pd.Series | dict) -> dict:
    return {"month": row["month"], "region": row["region"], "product": row["product"]}


def plant_issues(clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Return (file_a, file_b, answer_key) with six known problems planted."""
    a = clean.copy()
    b = clean.copy()
    key: list[dict] = []

    # 1. Subtotal rows mixed into the data (the "9.6x" problem).
    #    One labelled "Total", one with a blank product name.
    subtotal_rows = []
    for region, month, label in [("North", "2025-03", "Total"), ("South", "2025-06", "")]:
        block = a[(a["region"] == region) & (a["month"] == month)]
        subtotal_rows.append(
            {
                "month": month,
                "region": region,
                "product": label,
                "unit": "cases",
                "volume": int(block["volume"].sum()),
                "revenue_gbp": round(float(block["revenue_gbp"].sum()), 2),
            }
        )
    key.append(
        {
            "issue_id": 1,
            "issue_type": "subtotal_row",
            "file": "A",
            "severity": "critical",
            "rows": [_key(r) for r in subtotal_rows],
            "description": "Region subtotal rows mixed in with product rows; summing the "
            "column double-counts those region-months.",
        }
    )

    # 2. Exact duplicate rows (e.g. an extract run twice and appended).
    dup_idx = a[(a["month"] == "2025-04") & (a["region"] == "East")].index[:3]
    duplicates = a.loc[dup_idx]
    key.append(
        {
            "issue_id": 2,
            "issue_type": "duplicate_row",
            "file": "A",
            "severity": "high",
            "rows": [_key(r) for _, r in duplicates.iterrows()],
            "description": "Three rows appear twice.",
        }
    )

    # 3. Missing month: East has no rows at all for August.
    missing_mask = (a["region"] == "East") & (a["month"] == "2025-08")
    key.append(
        {
            "issue_id": 3,
            "issue_type": "missing_period",
            "file": "A",
            "severity": "high",
            "rows": [{"month": "2025-08", "region": "East", "product": None}],
            "description": "All East rows for 2025-08 are missing from File A.",
        }
    )
    a = a[~missing_mask]

    # 4. Region total mismatch: finance booked a manual adjustment in West, October.
    adj_mask = (b["region"] == "West") & (b["month"] == "2025-10") & (b["product"] == "Cola 500ml")
    b.loc[adj_mask, "revenue_gbp"] = (b.loc[adj_mask, "revenue_gbp"] - 2500.00).round(2)
    key.append(
        {
            "issue_id": 4,
            "issue_type": "reconciliation_gap",
            "file": "B",
            "severity": "high",
            "rows": [_key(r) for _, r in b[adj_mask].iterrows()],
            "description": "Finance revenue for West 2025-10 is GBP 2,500.00 lower than the "
            "sales system (an unexplained manual adjustment).",
        }
    )

    # 5. Unit mix-up: one row entered in bottles but still labelled "cases".
    #    Volume is x24, revenue is correct, so the implied price per case collapses.
    unit_mask = (a["region"] == "South") & (a["month"] == "2025-05") & (a["product"] == "Lemon Soda 330ml")
    a.loc[unit_mask, "volume"] = a.loc[unit_mask, "volume"] * BOTTLES_PER_CASE
    key.append(
        {
            "issue_id": 5,
            "issue_type": "unit_mismatch",
            "file": "A",
            "severity": "critical",
            "rows": [_key(r) for _, r in a[unit_mask].iterrows()],
            "description": "Volume recorded in bottles (x24) while the unit says cases.",
        }
    )

    # 6. Extreme outlier: a typo adds a zero to both volume and revenue (x10).
    #    The price per case stays normal, so only the size gives it away.
    out_mask = (a["region"] == "North") & (a["month"] == "2025-11") & (a["product"] == "Orange Juice 1L")
    a.loc[out_mask, "volume"] = a.loc[out_mask, "volume"] * 10
    a.loc[out_mask, "revenue_gbp"] = (a.loc[out_mask, "revenue_gbp"] * 10).round(2)
    key.append(
        {
            "issue_id": 6,
            "issue_type": "outlier",
            "file": "A",
            "severity": "high",
            "rows": [_key(r) for _, r in a[out_mask].iterrows()],
            "description": "Volume and revenue are 10x the normal level for this product/region.",
        }
    )

    # Assemble File A the way a messy export looks: subtotals sit right after
    # their region-month block, duplicates are appended at the end.
    a = a.sort_values(["month", "region", "product"]).reset_index(drop=True)
    parts = []
    for (month, region), block in a.groupby(["month", "region"], sort=True):
        parts.append(block)
        for s in subtotal_rows:
            if s["month"] == month and s["region"] == region:
                parts.append(pd.DataFrame([s], columns=COLUMNS))
    parts.append(duplicates)
    a = pd.concat(parts, ignore_index=True)

    return a, b.reset_index(drop=True), key


def main(out_dir: str | Path = "data", seed: int = SEED) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    clean = generate_clean(seed)
    file_a, file_b, key = plant_issues(clean)

    file_a.to_csv(out / "sales_system.csv", index=False)
    file_b.to_csv(out / "finance_report.csv", index=False)
    with open(out / "answer_key.json", "w", encoding="utf-8") as f:
        json.dump(key, f, indent=2)

    print(f"File A (sales system):   {len(file_a)} rows -> {out / 'sales_system.csv'}")
    print(f"File B (finance report): {len(file_b)} rows -> {out / 'finance_report.csv'}")
    print(f"Answer key: {len(key)} planted issues -> {out / 'answer_key.json'}")
    for item in key:
        print(f"  #{item['issue_id']} [{item['severity']}] {item['issue_type']} (file {item['file']})")


if __name__ == "__main__":
    main()