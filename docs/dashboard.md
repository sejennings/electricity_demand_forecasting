# Using the dashboard

Start it from the project folder:

```powershell
.venv/Scripts/python.exe -m scripts.serve_dashboard
```

Open [localhost:8870](http://127.0.0.1:8870/). Add `--port 8871` if that port is busy.
Stop the server with Ctrl+C.

## Refreshing data

**Update from AWS** fetches current forecasts, scores and job status. It needs a
valid AWS CLI session and may take up to two minutes. Updates happen only when
you ask; there is no background polling. Wait a minute between updates.

**Reload saved view** just rereads `dashboard/snapshot.json`. It does not contact
AWS. That is why reloading an old snapshot does not make its timestamp newer.

If your AWS session has expired, sign in again and retry. You can also export from
a terminal:

```powershell
.venv/Scripts/python.exe -m scripts.export_dashboard
```

An update failure keeps the last saved snapshot. The page warns when data is old
or a refresh fails, rather than quietly replacing it with demo data.

## Reading the results

Choose a forecast issue and UTC or Eastern time. The chart compares its original
predictions with available actual demand. WAPE and MAE cover **scored hours only**;
pending hours are not treated as zero. CSV download includes the selected issue.

The pipeline panel shows recent jobs, including failures. A fresh snapshot can
still contain an older forecast if newer forecast jobs failed.

[Demo mode](http://127.0.0.1:8870/?demo=1) uses clearly labeled synthetic data.

## Local access and export limits

The server binds to your computer, serves only dashboard files, and accepts AWS
update requests only from its own page. AWS credentials stay in the local CLI
session, never in browser code. No cloud resources are created.

Exports keep the newest 30 issues by default. Use `--limit` for 1–100 issues.
Discovery stops above 500 manifests; review archive size before raising
`--max-manifests`. Requests have small AWS usage costs. Snapshots are ignored by Git.
