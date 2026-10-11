import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app import main as m


class Explain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_client, cls.old_db = m.client, m.db
        m.client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'), tz_aware=True)
        cls.name = 'attendance_phase4_test_' + uuid4().hex
        m.db = m.client[cls.name]
        cls.api = TestClient(m.app)
        cls.api.__enter__()
        cls.api.post('/employees', json={'emp_code': 'EMP0001', 'name': 'Test',
            'email': 'test@example.com', 'department': 'Engineering', 'joined_on': '2026-01-01'})
        cls.api.post('/attendance/punch-in', json={'emp_code': 'EMP0001', 'punched_at': 1783310400000})

    @classmethod
    def tearDownClass(cls):
        m.client.drop_database(cls.name)
        cls.api.__exit__(None, None, None)
        m.client, m.db = cls.old_client, cls.old_db

    def test_real_index_plans(self):
        for endpoint, query in [('attendance_list', 'emp_code=EMP0001&page=2&page_size=5'),
                ('employee_monthly', 'emp_code=EMP0001&month=2026-07'),
                ('department_summary', 'month=2026-07'), ('late_leaderboard', 'month=2026-07'),
                ('department_trend', 'department=Engineering&from=2026-07-01&to=2026-07-03')]:
            response = self.api.get('/admin/explain/'+endpoint+'?'+query)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('IXSCAN', response.text)
            self.assertNotIn('COLLSCAN', response.text)
            self.assertIn('executionStats', response.text)

    def test_missing_and_bad_parameters(self):
        for query in ['employee_monthly?month=2026-07', 'department_summary',
                      'department_trend?department=Engineering', 'unknown',
                      'attendance_list?page=0', 'attendance_list?date_from=bad',
                      'late_leaderboard?month=2026-13']:
            self.assertEqual(self.api.get('/admin/explain/'+query).status_code, 422)

    def test_shared_query_builders(self):
        command = m.attendance_command('EMP0001', '2026-07-01', '2026-07-31', 'PRESENT', 3, 7)
        self.assertEqual(command['skip'], 14)
        self.assertEqual(command['limit'], 7)
        with patch.object(m.db, 'command', return_value={}) as explain:
            self.api.get('/admin/explain/attendance_list?emp_code=EMP0001&date_from=2026-07-01&date_to=2026-07-31&status=PRESENT&page=3&page_size=7')
            self.assertEqual(explain.call_args.args, ('explain', command))
