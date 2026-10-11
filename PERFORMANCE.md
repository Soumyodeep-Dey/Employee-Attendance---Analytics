# Performance verification

Local MongoDB 7, 1,000 employees and 100,000 attendance records in an isolated temporary database.
Indexes created after seeding; startup took 0.53 seconds. All plans contained IXSCAN and no COLLSCAN.
Timings are one local run, not production guarantees. Expected aggregate totals were also checked.

| Endpoint | Parameters | Response time (ms) |
| --- | --- | ---: |
| attendance_list | (defaults) | 24.94 |
| attendance_list | emp_code=EMP0001&page=2&page_size=10 | 2.99 |
| attendance_list | status=PRESENT&date_from=2026-07-01&date_to=2026-07-31 | 9.1 |
| employee_monthly | emp_code=EMP0001&month=2026-07 | 4.26 |
| department_summary | month=2026-07 | 185.72 |
| department_summary | month=2026-07&department=Engineering | 94.18 |
| late_leaderboard | month=2026-07&limit=1 | 62.26 |
| late_leaderboard | month=2026-07&department=Engineering&limit=1 | 59.73 |
| department_trend | department=Engineering&from=2026-07-01&to=2026-07-31 | 748.61 |
