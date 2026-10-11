# Phase 1: foundation and starter review

Python runs FastAPI on port 8000. MongoDB runs separately on port 27017.
The default connection is local MongoDB; Atlas works by setting MONGO_URI.

Completed: timezone-aware storage, whole-second punch truncation, strict request
validation, decimal half-up duration rounding, overnight shift helpers, startup
indexes, readiness ping, employee creation/listing, race-safe punch-in, and
database-side attendance pagination. Response serialization handles nested
audit dates and supplies defaults for legacy fields.

Pending: punch-out, manual correction, all analytics, explain endpoint, final
DECISIONS.md, and performance validation. Index choices will be verified against
the final analytics pipelines rather than assumed correct.

## Windows setup

Install Python 3.11+ if using a normal terminal, then run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start Docker Desktop, then create the database container once:

```powershell
docker run -d --name hrone-attendance-mongo-dev -p 127.0.0.1:27018:27017 -v hrone-attendance-data:/data/db mongo:7
```

On later visits, use `docker start hrone-attendance-mongo-dev`.

```powershell
$env:MONGO_URI = 'mongodb://localhost:27018'
$env:MONGO_DB = 'attendance_db'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
```

Open http://localhost:8000/docs for interactive requests.
Load the kit samples only into a disposable local database: `sample_seed.py`
deletes existing documents in both collections before loading samples.

For Atlas, replace MONGO_URI with your private Atlas connection string. Configure
database credentials and allow the connecting machine's IP in Atlas. Never commit
the connection string. Real environment variables take precedence over .env.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use a uniquely named local database and drop only that database afterward.
The supplied problem statement, contract and sample dataset are excluded from Git
to avoid publishing the hiring kit.

