# Historical evaluation: Duke Energy Carolinas

Run date: October 17, 2026. Full machine-readable results, monthly coverage, configuration,
library version and input SHA-256 are in `historical_evaluation.json`.

## Data quality

2021–2025 EIA DUK UTC demand: 43,823 / 43,824 expected hours. The missing hour is
2025-11-03 05:00 UTC. No null or nonpositive recorded demand values. No interpolation.
Charlotte ERA5 weather: all 43,824 hours, no nulls in requested fields. Weather is
stored for exploration but excluded from these predictors to avoid future-weather leakage.
These checks establish completeness, not a guarantee that all source measurements are correct.

Demand source: https://www.eia.gov/opendata/bulk/EBA.zip, series `EBA.DUK-ALL.D.H`.
Weather source: https://open-meteo.com/en/docs/historical-weather-api (ERA5).

## Protocol

Initial training history: 2021–2023. Validation: 2024. Chronological holdout: 2025.
Each month refits on expanding history, using only target labels strictly before the
monthly issue time minus 24 hours. Within a month, the fitted estimator stays fixed.
Past holdout observations enter later scheduled refits, as they would in operation;
this is prequential evaluation, not a model frozen at the beginning of 2025.
No hyperparameter search or tuning used 2025 results.

Forecast issuance is midnight UTC; targets cover that UTC day's 24 hours. Demand inputs
must be strictly earlier than issue time minus an assumed 24-hour reporting delay.
The daily naive baseline therefore repeats the most recent available daily pattern,
which is two days earlier under this delay. This differs from the earlier optimistic
zero-delay January experiment. Revised historical data cannot prove real-time availability.

Gradient boosting uses target UTC hour, weekday, month and annual sine/cosine; available
24/48/168/336-hour seasonal demand lags; and last/mean/min/max demand in the 24 hours
before the availability cutoff. Seasonal lag timestamps repeat backward if needed.
Fixed settings: 200 boosting iterations, 15 leaves, learning rate 0.05, L2 10,
seed 42, and early stopping disabled to avoid random validation splits.

All models share identical complete evaluation days. 2024: 366 days / 8,784 hours.
2025: 361 days / 8,664 hours. Four November days are excluded due to the missing
target/source hour and its effect on required features. Metrics below weight hours equally.

## Results

| Model | 2024 WAPE | 2025 WAPE | 2025 MAE (MW) | 2025 RMSE (MW) |
| --- | ---: | ---: | ---: | ---: |
| Persistence | 18.84% | 18.62% | 2,337.48 | 3,098.76 |
| Daily naive | 10.08% | 10.40% | 1,305.22 | 1,761.14 |
| Weekly naive | 11.58% | 12.93% | 1,622.87 | 2,231.36 |
| Daily/weekly mean | 9.04% | 10.03% | 1,258.56 | 1,691.99 |
| Gradient boosting | 7.79% | 8.28% | 1,038.65 | 1,406.91 |

Gradient boosting improves 2025 WAPE by 17.5% relative to the best baseline.
MAE at each day's actual peak hour falls from 1,606.19 MW to 1,517.60 MW (5.5%).
This metric measures error at the actual peak hour, not peak-time prediction accuracy.

| 2025 season | Daily/weekly WAPE | Gradient boosting WAPE |
| --- | ---: | ---: |
| Winter (Jan, Feb, Dec) | 14.35% | 11.37% |
| Spring (Mar–May) | 8.68% | 7.03% |
| Summer (Jun–Aug) | 8.82% | 7.23% |
| Fall (Sep–Nov) | 7.64% | 7.09% |

Winter remains the hardest season. Weather forecasts, holidays and additional regional
weather locations are next model improvements. Confidence intervals and operational
publication-time validation remain future work; these results are retrospective.

## AWS milestone

The local multi-season pipeline now supports the first AWS milestone: storage and
scheduled ingestion. Set up the project AWS environment and a budget alert before
provisioning. Keep the first deployment focused on versioned raw/processed storage,
credentials and scheduled incremental imports. Verify source publication latency before
automating forecast issuance. Model training and evaluation can continue locally.
