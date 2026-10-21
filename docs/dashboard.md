# Forecast operations dashboard

A dependency-free static dashboard with read-only exports from the existing AWS
lake and Step Functions workflows. It creates no hosting resources, runs no
Athena queries and requires no API keys or AWS credentials in the browser.

From the repository root in PowerShell:

```powershell
# Requires the existing AWS optional dependencies and a valid default CLI session.
.venv/Scripts/python.exe -m scripts.export_dashboard
.venv/Scripts/python.exe -m http.server 8870 --bind 127.0.0.1 --directory dashboard
```

Open [the local dashboard](http://127.0.0.1:8870/). The export reads at most 30
issues by default (`--limit 1` through `100`), sorts by actual issue time and
atomically replaces the ignored `dashboard/snapshot.json`. It lists and reads all
forecast manifests to discover issues by actual issue time, then reads the latest
score revisions for the selected issues. Consequently exports still incur small S3 request
charges; repeatedly exporting a large archive increases request usage. It reads
five recent executions per pipeline. No cloud state or forecasts are modified.

The browser reads only that snapshot. **Refresh view reloads the local snapshot;
it does not export new AWS data.** Run the export command again for current data.
Snapshot time and stale snapshots are shown. Serving only `dashboard/` prevents
the web server from exposing repository configuration, state or credentials.
Keep the server bound to loopback.

Features: issue selection, UTC/Eastern display, forecast/actual chart, pending
actual gaps, per-issue WAPE and MAE, scoring coverage, hourly values, CSV download,
recent pipeline status and forecast provenance. WAPE is computed only on scored
hours of the selected issue. Early prospective metrics are not multi-season
model evaluations. Separate issues are never silently combined.

If no export exists, the page offers [demo mode](http://127.0.0.1:8870/?demo=1).
Demo data is synthetic, explicitly labeled and never automatically substituted
for missing real data. Production snapshots and downloaded datasets are ignored
by Git. No external JavaScript, font CDN or analytics calls are used.

This first version is local. Public AWS hosting and automated snapshot updates
can be added later after reviewing costs and access requirements.
