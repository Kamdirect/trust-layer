# Decision memo: automated checks before month-end reporting

**To:** Head of Finance Operations · **Re:** whether to run Trust Layer before figures
are shared · **Basis:** synthetic test data with planted problems; no real company data

## Decision

**Run Trust Layer on every sales-system extract before month-end figures are shared, in
place of the manual checklist. Route unexplained gaps to finance and everything else to the
data team. Check one known weakness by hand: a "unit mix-up" in the finance file.**

## Evidence: the three findings that matter

1. **It finds almost everything, with no more work for the analyst.** On 200 independent
   test cases it found **99.9%** of planted problems, against **84.8%** for a careful
   manual checklist. That is with **5.2 items to review per case, against 4.8**.
   A VLOOKUP-style exact match needed **61 items per case**, and 9 in 10 of them were
   harmless credit notes.
2. **The gain is entirely on errors entered in the source system.** When a wrong value or a
   unit mix-up is in **both** files, comparing the files cannot see it: the checklist caught
   **4%** of these, Trust Layer **99%**. These are also the errors most likely to reach a
   management report, because both versions agree.
3. **The biggest problems come first.** Each issue shows the money and volume at stake, and
   says what to check next. On the sample data, the top item was subtotal rows
   double-counting **£103,854**.

## Trade-offs and risks

| Risk | Size | Mitigation |
|---|---|---|
| **False alarms**: 40% of clean cases raised at least one flag, mostly from the 0.1% gap tolerance meeting small credit notes | ~0.6 false items per case | Set the tolerance with finance. Wider means fewer alarms, but small real gaps are missed |
| **Mislabelled finance adjustments**: 11% were flagged as a unit mix-up in the finance file and marked "explained" | The row is still flagged, but it goes to the wrong team | Until it's fixed, send any unit mix-up in the finance file to finance |
| **Unanticipated problem types**: every test was built by the tool's author | Unknown | Log every problem found by hand that the tool missed, and add a check for it |
| **Thresholds tuned on synthetic data** (8% noise) | False alarms may differ on real extracts | Run in parallel with the current checklist for one month-end, and compare |

## Recommendation and next steps

| Step | Owner | When | Go/no-go test |
|---|---|---|---|
| 1. Run Trust Layer alongside the existing checklist for one month-end close | Finance operations | Next close | It finds everything the checklist finds |
| 2. Agree the gap tolerance with finance | Finance controller | Before step 3 | False alarms at a level the team will act on |
| 3. Replace the checklist with Trust Layer | Finance operations | Following close | No problem found by hand that the tool missed |
| 4. Fix gap matching so an explained gap must match the issue's amount, not just its place | Data team | Within a quarter | The mislabelled adjustments fall from 11% to near zero on the same test cases |

## What would change this recommendation

- **Real extracts with many more false alarms** than the test cases: tune the tolerance first.
- **Source systems that rarely make entry errors:** then the gain over the checklist is small.
  The checklist already catches extract problems.
- **Problems the tool doesn't cover** turning up in the parallel run: add checks before replacing anything.
