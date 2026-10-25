# Does Trust Layer beat what an analyst would do anyway?

**Question:** compared with the two approaches an analyst would normally use, does Trust
Layer find more real problems, raise fewer false alarms, or save review effort?

**Answer:**
- It finds almost every problem: **99.9%**, against about 85% for both alternatives.
- With about the same number of items to review: **5.2 per case**, against 4.8 for a simple
  rule checklist.
- The whole difference comes from **errors that exist in both files**. Comparing the files
  cannot see those: Trust Layer caught 99%, a simple checklist 4%.
- **It is not better at everything.** It still raised a false alarm in 40% of clean cases,
  and it mislabelled 11% of finance adjustments as unit mix-ups.

Reproduce with `python -m scripts.compare_methods`. Results are saved in
[method_comparison.csv](method_comparison.csv),
[method_comparison_by_type.csv](method_comparison_by_type.csv) and
[method_comparison_results.csv](method_comparison_results.csv).

## 1. The three approaches

| Approach | What it does | Represents |
|---|---|---|
| **Exact match** | Totals each month-region-product in both files, and flags every line that differs (revenue to the nearest £1, volume exactly) or exists in only one file | VLOOKUP or a pivot table comparison |
| **Simple rules** | Flags rows labelled "total" or with a blank product, exact duplicate rows and blank cells. Then compares region-month totals and flags any gap over 0.1% | A careful analyst's standard checklist, with no statistics |
| **Trust Layer** | Every check in `src/checks.py`: structure first, then blanks, missing periods, unit consistency, seasonally adjusted outliers, and reconciliation that labels each gap explained or unexplained | This project |

## 2. The independent test cases

`src/independent_cases.py` was written **after the checks were finished**. It differs from
the development data on purpose:

| | Development data | Independent cases |
|---|---|---|
| Business shape | Always 4 regions, 6 products, same seasonality and noise | 3–6 regions, 5–9 products, random prices, seasonal strength, peak month and noise |
| Harmless differences between the files | None | Finance books small credit notes and price corrections (up to 0.3%) on ~15% of rows. **These are not problems** |
| Problems | Always the same 6, at the same sizes | Each type appears with probability 0.6, at a random place and size |
| Subtotal labels | "Total", blank | Also "TOTAL", "Sub-total", "Region total", **"All products"** |
| Wrong values | ×10 only | **×2, ×3, ×5, ×10 and ×0.1** (a dropped zero) |
| Unit mix-ups | Packs of 24 | Packs of 6, 12 or 24 |
| Blank cells | Never planted | **A new problem type** |
| Where an error sits | Always in the extract (file A) | Unit mix-ups and wrong values are in **both files** half the time: entered in the source system |
| Clean cases | None | 20% of cases have no problems, to measure false alarms |

**Procedure:**
- The comparison code was debugged on cases 900–939.
- The reported run uses **cases 1000–1199** (200 cases: 40 clean, with 682 planted problems).
- It was run once, and **the checks were not changed after seeing the results.**

## 3. How every approach is scored

- **A flag** is one item an analyst must look at: a row, or a whole region-month.
- **A planted problem is detected** when every one of its rows is covered by a flag, of any
  type, in the same place. The baselines are not penalised for being unable to say *what* is
  wrong.
- **Recall** = planted problems detected ÷ problems planted.
- **Precision** = flags that point at a real problem ÷ all flags.
- **False alarms on clean cases** = the share of problem-free cases that raised any flag.
- **Review effort** = flags per case. This is measured, not a guess at minutes.

## 4. Results

| | Exact match | Simple rules | Trust Layer |
|---|---|---|---|
| Problems detected (recall) | 86.5% | 84.8% | **99.9%** |
| Flags that were real problems (precision) | 10.5% | 85.6% | **89.3%** |
| Clean cases with any false alarm | 100% | 47.5% | **40.0%** |
| Items to review per case | 60.8 | **4.8** | 5.2 |
| False alarms per case | 54.4 | 0.7 | **0.6** |
| Time per case (varies by computer) | ~60 ms | **~20 ms** | ~40 ms |

**By problem type** (share detected):

| Problem | Exact match | Simple rules | Trust Layer |
|---|---|---|---|
| Subtotal row | 100% | 100% | 100% |
| Duplicate rows | 100% | 100% | 100% |
| Missing period | 100% | 100% | 100% |
| Finance gap | 100% | 100% | 100% |
| Blank value | 100% | 100% | 100% |
| Unit mix-up | 52.6% | 43.3% | **100%** |
| Wrong value | 50.5% | 47.3% | **98.9%** |

**Where the difference comes from:**

| Unit mix-ups and wrong values | Exact match | Simple rules | Trust Layer |
|---|---|---|---|
| Error in file A only | 100% | 100% | 100% |
| Error in **both** files | 14.8% | 3.7% | **99.1%** |

When an error is in only one file, comparing the files finds it, and every approach succeeds.
When it was entered in the source system and is in both files, comparison cannot see it.
Trust Layer's within-file checks (price per unit, and expected volume for that product,
region and month) still can. The baselines' few "detections" there are coincidences: an
unrelated flag that happened to fall in the same region-month.

**Wrong values by size** (Trust Layer): ×0.1, ×3, ×5 and ×10 were all caught. ×2 was caught
93% of the time; the one miss in the whole run was a ×2 error present in both files.

## 5. What Trust Layer gets wrong

- **Finance adjustments mislabelled (12 of 106, 11%).** A large adjustment on a small row
  makes that row's price per unit look implausible. So Trust Layer flags it as a *unit
  mix-up* and marks the region-month gap as *explained*. The analyst does see the row, but
  it would be routed to the data team instead of finance. The cause is a limitation already
  stated in the README: gaps are matched to issues by place, not by amount. This is the
  next fix to make.
- **False alarms on 40% of clean cases.** Almost all come from the 0.1% reconciliation
  tolerance meeting the harmless credit notes. The simple checklist uses the same tolerance
  and has the same problem (47.5%). A wider tolerance would cut false alarms but miss small
  real gaps. That choice belongs to the business, not the code.
- **Slightly more review items than the checklist** (5.2 against 4.8 per case), because it
  flags at row level, and because it finds the both-file errors the checklist misses.

## 6. Limits of this test

- **The test cases are still synthetic and written by the tool's author.** They are
  independent of the development data, but problem types nobody thought of are, by
  definition, not in them.
- **"Detected" means the right place was flagged,** not that the analyst would understand
  why. Trust Layer also names the problem type (it named the right type for 97.9% of
  problems); the baselines don't.
- **Time is computer time, not analyst time.** All three run in well under a second. What
  differs is the number of items a person must review, and whether each one says what to check.
