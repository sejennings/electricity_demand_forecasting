# Public dashboard costs

GitHub Pages serves the dashboard and portfolio. AWS publishes a small JSON
summary twice daily; visitors can read that object but cannot list or write
objects, access the lake, or run jobs.

The planning estimate adds a $1 monthly allowance for publishing and public
data traffic, plus one $0.10 error alarm. This includes a scenario of 10,000
dashboard loads per month and the maximum 1 MiB summary. Actual summaries are
smaller. The existing Lambda/API allowance also remains in place.

`python scripts/estimate_monthly_cost.py` includes this addition. It keeps the
normal and stress scenarios below the project's $10 monthly target, without
subtracting credits. Visitor volume is an assumption, not a hard spending cap.

Sources: [S3 pricing](https://aws.amazon.com/s3/pricing/),
[Lambda pricing](https://aws.amazon.com/lambda/pricing/), and
[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/).

The publisher has a two-minute timeout, no public invocation endpoint, no async
function retries, and a twice-daily schedule with one delivery retry. Logs expire
after seven days. It overwrites one object; it does not accumulate public data
versions or run training. The project quota requires shared Lambda concurrency;
reserved concurrency is unavailable. The existing budget alerts remain active.
