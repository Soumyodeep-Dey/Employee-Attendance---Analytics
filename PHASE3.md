# Phase 3: MongoDB analytics

All pipelines and routes live in app/main.py. Pipeline builders are separate
from endpoint execution so Phase 4 can explain the exact same queries.

| Route | Pipeline approach |
| --- | --- |
| GET /analytics/employees/{emp_code}/monthly?month=2026-07 | Employee lookup, grouped stored metrics, MongoDB calendar weekdays from joined_on |
| GET /analytics/departments/summary?month=2026-07 | Eligible employees first, per-employee log lookup, department grouping; record-weighted hours average |
| GET /analytics/leaderboard/late?month=2026-07&limit=10 | Monthly logs grouped by employee, employee join, department filter, $rank, rank cutoff, stable sort |
| GET /analytics/departments/{department}/trend?from=2026-07-01&to=2026-07-31 | Database-generated calendar, daily employee/log lookups, weekday rates and $setWindowFields seven-row average |

Missing legacy fields use zero/false defaults. Weekend presence contributes to
trend counts, but monthly present_days excludes weekends. Late/overtime totals
include weekends. Orphan logs are excluded from cross-collection reports.
Half-up rounding uses decimal arithmetic in MongoDB, avoiding $round ties-to-even.
Null rates are excluded from moving averages; the requested range bounds the window.

Tests use isolated databases rather than changing attendance_db. They cover no-log
employees, future and mid-month joiners, missing dates, weekends, cutoff ties and
rank skips, half-up averages, zero denominators and invalid query parameters.

Docker rebuild: `docker compose -f compose.local.yaml up -d --build --wait`.
Swagger: http://localhost:8001/docs. Compass: mongodb://127.0.0.1:27018.

Phase 4 remains: explain executionStats, index-plan verification at 100k records,
and the final DECISIONS.md/submission audit.
