# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | compute_late_minutes | Uses the instant's timezone for shift start | UTC punch compared with 09:30 UTC instead of IST | Build IST shift boundaries |
| 2 | compute_late_minutes | Floors before testing grace | 09:40:01 incorrectly gives 0 | Compare seconds > 600, then floor minutes |
| 3 | compute_work_hours | Float/banker's rounding | 4.505 hours must become 4.51 | Decimal division and ROUND_HALF_UP |
| 4 | compute_overtime | No 30-minute minimum | Five minutes overtime counted | Return zero below 30 whole minutes |
| 5 | compute_overtime | Overnight end on wrong day | 22:00-06:00 shift ends next day | Shared shift_bounds helper |
| 6 | health | Always returns ready | Database down still returns 200 | Ping MongoDB; return 503 on failure |
| 7 | create_employee | Check-then-insert race | Parallel creates can duplicate | Unique index and DuplicateKeyError -> 409 |
| 8 | create_employee | Naive server-local timestamp | Non-UTC host stores wrong instant | Aware UTC creation timestamp |
| 9 | responses | Datetimes serialized as strings | Contract expects integer milliseconds | Recursive date serializer |
| 10 | EmployeeIn | Missing constraints | Invalid code/email/date/time accepted | Field validators and calendar parsing |
| 11 | EmployeeIn | Equal shift times accepted | 09:30-09:30 creation | Model validator rejects equality |
| 12 | list_employees | First page skips a page | page=1 omits first 20 employees | (page-1)*page_size |
| 13 | list_employees | Total ignores filter | Department count includes everyone | Count same filter |
| 14 | list_employees | Missing deterministic sort | Pages depend on insertion order | Sort emp_code ascending |
| 15 | list endpoints | No pagination bounds | page=0, size=101 accepted | Query constraints |
| 16 | punch_in | Unknown employee dereferenced | Unknown code causes 500 | Explicit 404 |
| 17 | PunchInIn | Coerces strings/floats and accepts seconds | Timestamp string or seconds submitted | Strict bounded integer |
| 18 | PunchInIn | Any status accepted | ABSENT punch-in | Presence-status Literal |
| 19 | punch_in | Host-local date, no overnight mapping | Early overnight punch assigned to next day | UTC instant and IST attendance_date |
| 20 | punch_in | Milliseconds not truncated | 09:40:00.900 must store 09:40:00 | Integer seconds before calculations |
| 21 | punch_in | Check-then-insert race | Simultaneous identical punches | Unique employee/date index; duplicate -> 409 |
| 22 | punch_in, list_attendance | Leaks generated id | Response contains id | Strip internal _id; no generated API id |
| 23 | list_attendance | Loads entire filtered dataset | Memory/time grow with 100k logs | MongoDB sort/skip/limit and count |
| 24 | list_attendance | No tie-break sort | Equal dates have unstable order | date descending, emp_code ascending |
| 25 | list_attendance | Invalid/reversed dates accepted | Bad date or from > to | Parse calendar dates and return 422 |
| 26 | list_attendance | Missing legacy defaults | Missing history/half_day in seed | Supply defaults during serialization |
| 27 | startup | No indexes created | Duplicate races, slow queries | Idempotent startup index creation |

Examined and retained: synchronous PyMongo with normal def endpoints is valid
because FastAPI runs those handlers in its thread pool. Environment defaults are
allowed; load_dotenv(override=False) explicitly preserves injected variables.
Missing logs must remain missing, rather than inventing ABSENT records. Ignoring
extra request fields is intentional: the contract says derived inputs are ignored.

Phase 1 fixes the supplied endpoints and helpers. Missing punch-out, correction,
analytics and explain endpoints are tracked as unfinished implementation work.
Full explain/performance verification awaits the final pipelines.

Also note anything you looked at and decided was **not** a defect, and why.
