# Employee Attendance & Analytics API

Phases 1–3 are implemented: employee creation/listing, punch-in, punch-out,
attendance listing, manual corrections with audit history, validation, time
helpers, startup indexes and MongoDB readiness. Concurrent writes use unique
indexes and atomic snapshot comparisons.

Analytics includes employee monthly totals, department summaries, late rankings
with competition ties, and daily trends with a seven-day moving average. All
analytics run in MongoDB aggregation pipelines, including calendar gap filling.

Pending: explain endpoint, large-dataset performance checks and final design decisions.

Requires Python 3.11+ and MongoDB 6.0+ (local Docker or Atlas).
Install `requirements.txt`, set `MONGO_URI` and `MONGO_DB`, then run:

```powershell
uvicorn app.main:app --port 8000
```

See [PHASE1.md](PHASE1.md) for Windows setup and tests. Do not commit secrets,
virtual environments, the supplied hiring kit, data dumps or a Dockerfile.
