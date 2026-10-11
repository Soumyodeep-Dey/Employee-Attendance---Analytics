# Employee Attendance & Analytics API

Phase 1 is implemented: employee creation/listing, punch-in, attendance listing,
validation, time helpers, startup indexes and MongoDB readiness.

Pending: punch-out, corrections, analytics, explain and final design decisions.

Requires Python 3.11+ and MongoDB 6.0+ (local Docker or Atlas).
Install `requirements.txt`, set `MONGO_URI` and `MONGO_DB`, then run:

```powershell
uvicorn app.main:app --port 8000
```

See [PHASE1.md](PHASE1.md) for Windows setup and tests. Do not commit secrets,
virtual environments, the supplied hiring kit, data dumps or a Dockerfile.
