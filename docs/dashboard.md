# Forecast operations dashboard

A dependency-free static dashboard with read-only exports from the existing AWS
lake and Step Functions workflows. It creates no hosting resources, runs no
Athena queries and requires no API keys or AWS credentials in the browser.

From the repository root in PowerShell:

```powershell
# Requires the existing AWS optional dependencies and a valid default CLI session.
.venv/Scripts/python.exe -m scripts.export_dashboard
.venv/Scripts/python.exe -m scripts.serve_dashboard
```

Open [the local dashboard](http://127.0.0.1:8870/). The export displays at most 30
issues by default (`--limit 1` through `100`), sorts by actual issue time and
atomically replaces the ignored `dashboard/snapshot.json`. It lists and reads all
forecast manifests to discover issues by actual issue time, then reads the latest
score revisions for the selected issues. Discovery stops before downloading
manifests if the archive exceeds 500 issues; review its size before increasing
`--max-manifests`. Consequently exports still incur small S3 request
charges; repeatedly exporting a large archive increases request usage. It reads
five recent executions per pipeline. No cloud state or forecasts are modified.

The browser reads only that snapshot. **Refresh view reloads the local snapshot;
it does not export new AWS data.** Run the export command again for current data.
Snapshot time and stale snapshots are shown. Refresh preserves the selected issue,
and timezone changes re-render the loaded data without fetching it again. A failed
or malformed refresh retains the last valid view with an explicit warning.
Exports reject invalid or mismatched forecast/actual records; interrupted writes
leave the previous snapshot intact.

The launcher serves only known dashboard assets, binds to loopback and disables
HTTP caching. It works from any current directory and accepts `--port 8871` if
the default port is occupied. Stop it with Ctrl+C. It does not refresh AWS data.

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
