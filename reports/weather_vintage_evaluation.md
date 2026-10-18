# Weather-vintage evaluation

Weather features reduced paired WAPE from **10.7528% to 5.5601%**, a 48.29%
relative reduction, over 2,592 hours (108 complete days), July 1–October 16, 2026.
Both estimators use the same training samples, fixed gradient-boosting parameters,
monthly expanding refits and daily midnight UTC forecast origins. No days were skipped.

| Period | Demand-only WAPE | Weather-vintage WAPE |
|---|---:|---:|
| July | 13.7266% | 6.9890% |
| August | 9.1134% | 4.2350% |
| September | 9.8291% | 5.3927% |
| October 1–16 | 9.2391% | 5.5490% |
| Overall | 10.7528% | 5.5601% |

Overall MAE declined from 1,522.09 MW to 787.05 MW; RMSE from 1,982.34 MW
to 1,057.37 MW. This is a paired weather-feature ablation on 2026 data, distinct
from the earlier 2025 demand-only experiment with longer training history.

The backfill contains 197 GFS Seamless runs and 4,728 target hours, April 3–October
16. Each daily midnight origin uses the preceding day's 12 UTC run. The original
responses and hashes remain locally under ignored `data/weather-vintages/`.
Demand comes from EIA's official published Demand column, not adjusted or imputed
values, extended through October 16. Initial fitting uses April–June weather
history. Monthly training labels end strictly before the month minus 24 hours.

Historical weather availability is **assumed initialization + 12 hours**, not
measured publication time. Demand uses revised observations and an assumed 24-hour
delay. These are limitations of the retrospective simulation. No winter performance
is established, one Charlotte point represents DUK, and live hourly origins use
fresher weather than this daily fixed-run experiment. The score does not establish
hourly live-origin performance or justify a comparison with earlier-year scores.

The new artifact was trained in Docker on 4,704 labeled hours through the exclusive
cutoff October 16 at 00 UTC, with 19 input features. Offline Docker inference produces
24 future hourly predictions using weather and checks the source/schema and as-of
timestamps. AWS modeling deployment remains a separate step.

See [machine-readable metrics](weather_vintage_evaluation.json) for folds, source
hashes and detailed metrics, and [reproduction commands](../docs/weather-vintage-training.md).
