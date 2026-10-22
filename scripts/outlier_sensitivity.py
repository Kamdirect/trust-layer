"""How sensitive is the outlier check, and how often does it cry wolf?

Uses datasets with seeds 5000-5199, which were NOT used when choosing the threshold.
Run from the project root:  python -m scripts.outlier_sensitivity
"""

import numpy as np

from src.checks import check_outliers, validate_schema
from src.synthetic_data import generate_clean

SEEDS = range(5000, 5200)
MULTIPLIERS = [1.5, 2, 3, 10]

false_alarms = 0
detected = {m: 0 for m in MULTIPLIERS}
for seed in SEEDS:
    clean = validate_schema(generate_clean(seed), "A")
    false_alarms += bool(check_outliers(clean, "A"))

    # Corrupt one random row by each multiplier and see whether that exact row is flagged.
    row = int(np.random.default_rng(seed).integers(len(clean)))
    for m in MULTIPLIERS:
        corrupted = clean.copy()
        corrupted.loc[row, "volume"] = int(corrupted.loc[row, "volume"] * m)
        found = check_outliers(corrupted, "A")
        detected[m] += bool(found) and row in found[0].row_index

n = len(SEEDS)
print(f"Clean datasets with a false alarm: {false_alarms}/{n} ({100 * false_alarms / n:.1f}%)")
for m in MULTIPLIERS:
    print(f"Detects a x{m:<4} error: {detected[m]}/{n} ({100 * detected[m] / n:.1f}%)")