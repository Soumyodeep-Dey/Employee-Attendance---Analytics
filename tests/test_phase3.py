import os
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app import main as m


class Analytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_client, cls.old_db = m.client, m.db
        m.client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'), tz_aware=True)
        cls.name = 'attendance_phase3_test_' + uuid4().hex
        m.db = m.client[cls.name]
        cls.api = TestClient(m.app)
        cls.api.__enter__()
        for code, dept, joined in [('EMP0001', 'Engineering', '2026-07-01'),
                ('EMP0002', 'Engineering', '2026-07-07'), ('EMP0003', 'Engineering', '2026-07-01'),
                ('EMP0004', 'Sales', '2026-07-01'), ('EMP0005', 'Future', '2026-08-01')]:
            cls.api.post('/employees', json={'emp_code': code, 'name': code, 'email': code+'@example.com',
                         'department': dept, 'joined_on': joined})
        m.db.attendance_logs.insert_many([
            {'emp_code': 'EMP0001', 'date': '2026-07-06', 'status': 'PRESENT', 'work_hours': 8, 'late_minutes': 20},
            {'emp_code': 'EMP0001', 'date': '2026-07-07', 'status': 'WFH', 'half_day': True, 'work_hours': 3, 'late_minutes': 0},
            {'emp_code': 'EMP0001', 'date': '2026-07-11', 'status': 'ON_DUTY', 'work_hours': 10, 'late_minutes': 10, 'overtime_minutes': 40},
            {'emp_code': 'EMP0002', 'date': '2026-07-07', 'status': 'ON_DUTY', 'work_hours': 9, 'late_minutes': 30},
            {'emp_code': 'EMP0002', 'date': '2026-07-08', 'status': 'LEAVE'},
            {'emp_code': 'EMP0004', 'date': '2026-07-06', 'status': 'PRESENT', 'work_hours': None, 'late_minutes': 60},
            {'emp_code': 'EMP9999', 'date': '2026-07-06', 'status': 'PRESENT', 'late_minutes': 999}])

    @classmethod
    def tearDownClass(cls):
        m.client.drop_database(cls.name)
        cls.api.__exit__(None, None, None)
        m.client, m.db = cls.old_client, cls.old_db

    def get(self, path):
        response = self.api.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_employee_monthly(self):
        data = self.get('/analytics/employees/EMP0001/monthly?month=2026-07')
        self.assertEqual(data, {'emp_code': 'EMP0001', 'month': '2026-07', 'working_days': 23,
            'present_days': 1.5, 'leave_days': 0, 'late_count': 2, 'total_late_minutes': 30,
            'total_overtime_minutes': 40, 'attendance_pct': 6.52})
        joined = self.get('/analytics/employees/EMP0002/monthly?month=2026-07')
        self.assertEqual(joined['working_days'], 19)
        self.assertEqual(joined['leave_days'], 1)
        future = self.get('/analytics/employees/EMP0005/monthly?month=2026-07')
        self.assertEqual(future['working_days'], 0)
        self.assertIsNone(future['attendance_pct'])

    def test_summary_record_weighted_average(self):
        rows = self.get('/analytics/departments/summary?month=2026-07')['items']
        self.assertEqual([r['department'] for r in rows], ['Engineering', 'Sales'])
        self.assertEqual(rows[0], {'department': 'Engineering', 'headcount': 3, 'present_days': 2.5,
            'avg_work_hours': 7.5, 'late_count': 3, 'total_late_minutes': 60,
            'leave_count': 1, 'on_duty_count': 2})
        self.assertIsNone(rows[1]['avg_work_hours'])

    def test_ties_and_department_ranking(self):
        rows = self.get('/analytics/leaderboard/late?month=2026-07&limit=2')['items']
        self.assertEqual([r['emp_code'] for r in rows], ['EMP0004', 'EMP0001', 'EMP0002'])
        self.assertEqual([r['rank'] for r in rows], [1, 2, 2])
        rows = self.get('/analytics/leaderboard/late?month=2026-07&limit=1&department=Engineering')['items']
        self.assertEqual([r['rank'] for r in rows], [1, 1])

    def test_trend_gaps_weekends_headcount_and_window(self):
        rows = self.get('/analytics/departments/Engineering/trend?from=2026-07-06&to=2026-07-13')['items']
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]['headcount'], 2)
        self.assertEqual(rows[0]['attendance_rate'], 0.5)
        self.assertEqual(rows[1]['headcount'], 3)
        self.assertEqual(rows[1]['present_count'], 1.5)
        self.assertEqual(rows[2]['attendance_rate'], 0)
        self.assertEqual(rows[2]['moving_avg_7d'], 0.3333)
        self.assertEqual(rows[5]['present_count'], 1)
        self.assertIsNone(rows[5]['attendance_rate'])
        self.assertEqual(rows[7]['moving_avg_7d'], 0.1)
        empty = self.get('/analytics/departments/Future/trend?from=2026-07-06&to=2026-07-07')['items']
        self.assertEqual(len(empty), 2)
        self.assertIsNone(empty[0]['attendance_rate'])
        self.assertIsNone(empty[1]['moving_avg_7d'])
        weekend = self.get('/analytics/departments/Engineering/trend?from=2026-07-11&to=2026-07-12')['items']
        self.assertTrue(all(r['moving_avg_7d'] is None for r in weekend))

    def test_validation(self):
        for path, code in [('/analytics/employees/unknown/monthly?month=2026-07', 404),
            ('/analytics/departments/summary?month=2026-13', 422),
            ('/analytics/departments/summary?month=0000-01', 422),
            ('/analytics/leaderboard/late?month=2026-07&limit=0', 422),
            ('/analytics/departments/unknown/trend?from=2026-07-01&to=2026-07-01', 404),
            ('/analytics/departments/Engineering/trend?from=2026-07-02&to=2026-07-01', 422),
            ('/analytics/departments/Engineering/trend?from=2026-01-01&to=2026-04-03', 422)]:
            self.assertEqual(self.api.get(path).status_code, code)

    def test_competition_rank_skips_position(self):
        inserted = m.db.attendance_logs.insert_one({'emp_code': 'EMP0003', 'date': '2026-07-09',
            'status': 'PRESENT', 'late_minutes': 1}).inserted_id
        try:
            rows = self.get('/analytics/leaderboard/late?month=2026-07&limit=3')['items']
            self.assertEqual([r['rank'] for r in rows], [1, 2, 2])
            rows = self.get('/analytics/leaderboard/late?month=2026-07&limit=4')['items']
            self.assertEqual([r['rank'] for r in rows], [1, 2, 2, 4])
        finally:
            m.db.attendance_logs.delete_one({'_id': inserted})

    def test_half_up_average_over_stored_hours(self):
        self.api.post('/employees', json={'emp_code': 'EMP0010', 'name': 'Rounding',
            'email': 'round@example.com', 'department': 'Rounding', 'joined_on': '2026-07-01'})
        m.db.attendance_logs.insert_many([
            {'emp_code': 'EMP0010', 'date': '2026-07-01', 'status': 'PRESENT', 'work_hours': 1},
            {'emp_code': 'EMP0010', 'date': '2026-07-02', 'status': 'PRESENT', 'work_hours': 1.01}])
        try:
            row = self.get('/analytics/departments/summary?month=2026-07&department=Rounding')['items'][0]
            self.assertEqual(row['avg_work_hours'], 1.01)
        finally:
            m.db.attendance_logs.delete_many({'emp_code': 'EMP0010'})
            m.db.employees.delete_one({'emp_code': 'EMP0010'})
