# Employee Attendance & Analytics API

All assignment endpoints are implemented: employee creation/listing, punch-in, punch-out,
attendance listing, manual corrections with audit history, validation, time
helpers, startup indexes and MongoDB readiness. Concurrent writes use unique
indexes and atomic snapshot comparisons.

Analytics includes employee monthly totals, department summaries, late rankings
with competition ties, and daily trends with a seven-day moving average. All
analytics run in MongoDB aggregation pipelines, including calendar gap filling.

`GET /admin/explain/{endpoint}` returns executionStats for the same query or
pipeline used by the endpoint, including filters, sorting, pagination and hints.
20 automated tests pass. A 100,000-record local check verified index scans without
collection scans; results and limitations are in [PERFORMANCE.md](PERFORMANCE.md).
No known assignment features are missing. Hidden grader cases have not been run.

Requires Python 3.11+ and MongoDB 6.0+ (local Docker or Atlas).
Install dependencies, set `MONGO_URI` and `MONGO_DB`, then run:

```powershell
python -m pip install -r requirements.txt
$env:MONGO_URI = 'mongodb://localhost:27017'
$env:MONGO_DB = 'attendance_db'
uvicorn app.main:app --port 8000
```

Indexes are created automatically at startup. Real environment variables take
priority over a local .env. Dates and shifts use IST; API instants use integer
epoch milliseconds; stored instants are UTC BSON dates. Swagger is at /docs.

Tests: install requirements-dev.txt, then run `python -m unittest discover -s tests -v`.
Benchmark: `python tests/performance_check.py`. Both use disposable databases;
set MONGO_URI to the intended test server first. Review and design rationale are
in REVIEW.md and DECISIONS.md.

See [PHASE1.md](PHASE1.md) for Windows setup and tests. Do not commit secrets,
virtual environments, the supplied hiring kit, data dumps or a Dockerfile.
