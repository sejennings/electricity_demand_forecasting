# GridCast

GridCast forecasts hourly electricity demand for Duke Energy Carolinas. It combines
EIA demand data with weather forecasts, saves each forecast, and scores it when
actual demand arrives.

## Open the dashboard

[Public dashboard](https://sejennings.github.io/gridcast/) — AWS data refreshes
twice daily. No AWS sign-in is needed to view it.

From the project folder in PowerShell:

```powershell
.venv/Scripts/python.exe -m scripts.serve_dashboard
```

Open [localhost:8870](http://127.0.0.1:8870/). Use **Update from AWS** for fresh data
or **Reload saved view** to reread the existing snapshot. AWS updates need a valid
CLI sign-in. Use `--port 8871` if port 8870 is occupied.

[Dashboard guide](docs/dashboard.md) · [Demo](http://127.0.0.1:8870/?demo=1)

## First-time setup

Requires Python 3.11+; the pinned experiments use Python 3.12.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-model-lock.txt -r requirements-runtime-lock.txt
.venv/Scripts/python.exe -m pip install --no-deps -e .
```

For a snapshot without starting the dashboard:

```powershell
.venv/Scripts/python.exe -m scripts.export_dashboard
```

## How it works

- **Import:** Lambda collects demand and weather, then saves validated Parquet in S3.
- **Forecast:** a daily Fargate task produces the next 24 hourly predictions.
- **Score:** later imports add actual demand and update scores without changing the original forecast.
- **Explore:** Glue and Athena support SQL analysis; the dashboard shows individual forecasts and pipeline status.

Historical weather and live forecast weather stay separate. Missing demand is
never invented. A forecast fails if its required history is unavailable.

## Project guides

| Task | Guide |
|---|---|
| Import data or reproduce model experiments | [Data and models](docs/data-and-models.md) |
| Understand live inputs and Docker commands | [Operational model](docs/operational-model.md) |
| Train with archived weather forecasts | [Weather-vintage training](docs/weather-vintage-training.md) |
| Manage daily jobs and scores | [Scheduled forecasts](docs/scheduled-forecasts.md) |
| Review Terraform changes | [Infrastructure](infrastructure/README.md) |
| Configure GitHub deployment | [GitHub Actions](docs/github-actions-deployment.md) |
| Query the lake | [SQL analytics](sql/README.md) |

Results and dated deployment evidence are in [reports](reports/). They describe
past runs, not a guarantee of current accuracy or pipeline health.

## Checks and costs

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --check dashboard/app.js
```

The usage target is **$10/month before credits**. The local dashboard adds no
hosting bill; AWS updates make read-only API requests. Budget alerts and usage
checks reduce risk but do not guarantee a maximum bill. See the
[cost audit](docs/cost-audit-2026-10-18.md).

Keep credentials, downloaded data, model binaries, Terraform state and plans out
of Git. AWS resources belong in `us-east-2`.
