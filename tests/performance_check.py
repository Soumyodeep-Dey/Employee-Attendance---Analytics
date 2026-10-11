"""100k-record verification; writes/drops only its own UUID-named database."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app import main as m

name = 'attendance_performance_' + uuid4().hex
m.client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'), tz_aware=True)
m.db = m.client[name]
results = []
try:
    employees = [{'emp_code': f'EMP{i:04}', 'name': f'Employee {i}', 'email': f'e{i}@example.com',
        'department': 'Engineering' if i % 2 else 'Sales', 'shift_start': '09:30',
        'shift_end': '18:30', 'joined_on': '2026-01-01', 'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc)}
        for i in range(1, 1001)]
    m.db.employees.insert_many(employees)
    for offset in range(100):
        day = (date(2026, 5, 1) + timedelta(days=offset)).isoformat()
        m.db.attendance_logs.insert_many([{'emp_code': employee['emp_code'], 'date': day,
            'status': 'PRESENT', 'punch_in': None, 'punch_out': None, 'work_hours': 8.0,
            'late_minutes': 10, 'overtime_minutes': 0, 'half_day': False, 'history': []}
            for employee in employees])
    start = perf_counter()
    with TestClient(m.app) as api:
        startup = perf_counter() - start
        assert startup < 20, startup
        cases = [
            ('attendance_list', '', '/attendance'),
            ('attendance_list', 'emp_code=EMP0001&page=2&page_size=10', '/attendance'),
            ('attendance_list', 'status=PRESENT&date_from=2026-07-01&date_to=2026-07-31', '/attendance'),
            ('employee_monthly', 'emp_code=EMP0001&month=2026-07', '/analytics/employees/EMP0001/monthly'),
            ('department_summary', 'month=2026-07', '/analytics/departments/summary'),
            ('department_summary', 'month=2026-07&department=Engineering', '/analytics/departments/summary'),
            ('late_leaderboard', 'month=2026-07&limit=1', '/analytics/leaderboard/late'),
            ('late_leaderboard', 'month=2026-07&department=Engineering&limit=1', '/analytics/leaderboard/late'),
            ('department_trend', 'department=Engineering&from=2026-07-01&to=2026-07-31', '/analytics/departments/Engineering/trend')]
        for endpoint, query, route in cases:
            response = api.get('/admin/explain/'+endpoint+'?'+query)
            assert response.status_code == 200, response.text
            assert 'IXSCAN' in response.text, endpoint
            assert 'COLLSCAN' not in response.text, endpoint
            start = perf_counter()
            actual = api.get(route+'?'+query)
            elapsed = round((perf_counter()-start)*1000, 2)
            assert actual.status_code == 200, actual.text
            data = actual.json()
            if endpoint == 'employee_monthly':
                assert data['working_days'] == 23 and data['present_days'] == 23
                assert data['attendance_pct'] == 100 and data['total_late_minutes'] == 310
            elif endpoint == 'late_leaderboard':
                expected = 500 if 'department=' in query else 1000
                assert len(data['items']) == expected
                assert all(row['rank'] == 1 for row in data['items'])
            elif endpoint == 'department_summary':
                assert all(row['headcount'] == 500 and row['present_days'] == 11500 and row['avg_work_hours'] == 8 for row in data['items'])
            elif endpoint == 'department_trend':
                assert len(data['items']) == 31
                assert all(row['present_count'] == 500 and row['headcount'] == 500 for row in data['items'])
            results.append((endpoint, query or '(defaults)', elapsed))
        report = '# Performance verification\n\n'
        report += 'Local MongoDB 7, 1,000 employees and 100,000 attendance records in an isolated temporary database.\n'
        report += f'Indexes created after seeding; startup took {startup:.2f} seconds. All plans contained IXSCAN and no COLLSCAN.\n'
        report += 'Timings are one local run, not production guarantees. Expected aggregate totals were also checked.\n\n'
        report += '| Endpoint | Parameters | Response time (ms) |\n| --- | --- | ---: |\n'
        report += ''.join(f'| {endpoint} | {query} | {elapsed} |\n' for endpoint, query, elapsed in results)
        Path('PERFORMANCE.md').write_text(report, encoding='utf-8')
        print(report)
finally:
    # App shutdown closes its client, so cleanup needs its own short-lived one.
    with MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017')) as cleanup:
        cleanup.drop_database(name)
