import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from app import main as m


class Rules(unittest.TestCase):
    def test_boundaries(self):
        start, end = m.shift_bounds('2026-07-06', '09:30', '18:30')
        self.assertEqual(m.compute_late_minutes(start + timedelta(minutes=10), start), 0)
        self.assertEqual(m.compute_late_minutes(start + timedelta(minutes=10, seconds=1), start), 10)
        self.assertEqual(m.compute_overtime(end + timedelta(minutes=29, seconds=59), end), 0)
        self.assertEqual(m.compute_overtime(end + timedelta(minutes=30), end), 30)
        self.assertEqual(m.compute_work_hours(start, start + timedelta(seconds=16218)), 4.51)

    def test_overnight_and_history(self):
        ts = datetime(2026, 7, 7, 1, 0, tzinfo=m.IST)
        self.assertEqual(m.attendance_date(ts, '22:00', '06:00'), '2026-07-06')
        self.assertEqual(m.attendance_date(ts.replace(hour=6), '22:00', '06:00'), '2026-07-07')
        _, end = m.shift_bounds('2026-07-06', '22:00', '06:00')
        self.assertEqual(end.day, 7)
        doc = m.attendance_response({'_id': 'internal', 'history': [{'changes': {'punch_in': {'from': ts, 'to': None}}}]})
        self.assertNotIn('_id', doc)
        self.assertFalse(doc['half_day'])
        self.assertIsInstance(doc['history'][0]['changes']['punch_in']['from'], int)


class DatabaseAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = m.db
        cls.test_name = 'attendance_phase1_test_' + uuid4().hex
        m.db = m.client[cls.test_name]
        cls.api = TestClient(m.app)
        cls.api.__enter__()

    @classmethod
    def tearDownClass(cls):
        m.client.drop_database(cls.test_name)
        cls.api.__exit__(None, None, None)
        m.db = cls.original

    def test_full_flow_and_races(self):
        employee = {'emp_code': 'EMP0001', 'name': 'Test', 'email': 'test@example.com',
                    'department': 'Engineering', 'joined_on': '2026-07-01'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(lambda _: self.api.post('/employees', json=employee).status_code, range(4)))
        self.assertEqual(sorted(codes), [201, 409, 409, 409])
        page = self.api.get('/employees?department=Engineering').json()
        self.assertEqual(page['total'], 1)
        self.assertEqual(len(page['items']), 1)
        self.assertIsInstance(page['items'][0]['created_at'], int)
        punched_at = int(datetime(2026, 7, 6, 9, 40, 1, tzinfo=m.IST).timestamp()) * 1000 + 900
        body = {'emp_code': 'EMP0001', 'punched_at': punched_at}
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(lambda _: self.api.post('/attendance/punch-in', json=body).status_code, range(4)))
        self.assertEqual(sorted(codes), [201, 409, 409, 409])
        record = self.api.get('/attendance').json()['items'][0]
        self.assertEqual(record['late_minutes'], 10)
        self.assertEqual(record['punch_in'], punched_at - 900)
        self.assertNotIn('id', record)
        self.assertEqual(self.api.get('/health').status_code, 200)
        self.assertEqual(self.api.get('/employees?page=0').status_code, 422)
        self.assertEqual(self.api.get('/attendance?date_from=2026-07-09&date_to=2026-07-01').status_code, 422)
        for value in [1234567890, str(punched_at), float(punched_at), True, None]:
            self.assertEqual(self.api.post('/attendance/punch-in', json={**body, 'punched_at': value}).status_code, 422)
        self.assertEqual(self.api.post('/attendance/punch-in', json={'emp_code': 'unknown'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
