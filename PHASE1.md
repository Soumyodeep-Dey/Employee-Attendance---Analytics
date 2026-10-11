# Phase 1: foundation and starter review

## Run both services in Docker (local development)

Dockerfile builds Python, dependencies and app code into the API image.
compose.local.yaml starts that image and MongoDB together. These container files
are ignored by Git because the assignment forbids submitting a Dockerfile.

```powershell
docker compose -f compose.local.yaml up -d --build --wait
docker compose -f compose.local.yaml ps
docker compose -f compose.local.yaml logs -f api
```

Swagger: http://localhost:8001/docs. Health: http://localhost:8001/health.
Port 8001 on Windows forwards to 8000 inside the API container, avoiding a clash
with an API already running on Windows. API connects to mongodb://mongo:27017:
`mongo` is the Compose service hostname, not the Windows localhost.

MongoDB starts first; its healthcheck must pass before API startup. The API's
healthcheck calls /health, which pings MongoDB. The Compose database has its own
volume, hrone-attendance_mongo_data, separate from the earlier standalone database.
It starts empty; this is not a migration of standalone MongoDB data.
MongoDB is now published on Windows localhost port 27018 for Compass.
Connect Compass with `mongodb://127.0.0.1:27018` and select `attendance_db`.
The earlier standalone container must be stopped so it does not occupy this port.
To inspect MongoDB through a terminal:

```powershell
docker compose -f compose.local.yaml exec mongo mongosh attendance_db
```

After changing Python code, repeat the build/start command. Stop the stack with:

```powershell
docker compose -f compose.local.yaml down
```

This keeps its data volume. Do not add `-v` unless you intend to delete that data.
No Windows Python process or virtual environment is needed for this Docker mode.
The earlier standalone container can be stopped separately if no longer needed.

Python runs FastAPI on port 8000. MongoDB runs separately on port 27017.
The default connection is local MongoDB; Atlas works by setting MONGO_URI.

Completed: timezone-aware storage, whole-second punch truncation, strict request
validation, decimal half-up duration rounding, overnight shift helpers, startup
indexes, readiness ping, employee creation/listing, race-safe punch-in, and
database-side attendance pagination. Response serialization handles nested
audit dates and supplies defaults for legacy fields.

Phase 2 is also complete: punch-out and manual corrections with atomic snapshot
checks and append-only audit history. Ten tests pass across both phases, including
forced simultaneous punch-outs/corrections, legacy fields, overnight work,
24-hour boundaries and status transitions. Tests drop their own disposable databases.

Phase 3 analytics are now complete; see PHASE3.md for pipeline details.

Phase 4 is complete: explain endpoint, DECISIONS.md and performance validation.
The full suite contains 20 passing tests. PERFORMANCE.md records the 100k check.

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

