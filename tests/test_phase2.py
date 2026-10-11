import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pymongo import MongoClient
from app import main as m


def millis(hour, minute=0, second=0, day=6):
    return int(datetime(2026, 7, day, hour, minute, second, tzinfo=m.IST).timestamp()) * 1000


class AttendanceOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_client, cls.old_db = m.client, m.db
        m.client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'), tz_aware=True,
                               serverSelectionTimeoutMS=3000)
        cls.name = 'attendance_phase2_test_' + uuid4().hex
        m.db = m.client[cls.name]
        cls.api = TestClient(m.app)
        cls.api.__enter__()

    @classmethod
    def tearDownClass(cls):
        m.client.drop_database(cls.name)
        cls.api.__exit__(None, None, None)
        m.client, m.db = cls.old_client, cls.old_db

    def setUp(self):
        m.db.employees.delete_many({})
        m.db.attendance_logs.delete_many({})
        self.api.post('/employees', json={'emp_code': 'EMP0001', 'name': 'Test',
                      'email': 'test@example.com', 'department': 'Engineering', 'joined_on': '2026-07-01'})

    def punch(self, at=None):
        return self.api.post('/attendance/punch-in', json={'emp_code': 'EMP0001', 'punched_at': at or millis(9, 30)})

    def close(self, at):
        return self.api.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': at})

    def correct(self, **values):
        return self.api.patch('/attendance/EMP0001/2026-07-06', json={
            'reason': 'Biometric correction', 'regularized_by': 'hr.admin', **values})

    def test_close_and_repeated_close(self):
        self.punch()
        result = self.close(millis(19))
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data['work_hours'], 9.5)
        self.assertEqual(data['overtime_minutes'], 30)
        self.assertFalse(data['half_day'])
        self.assertEqual(data['history'], [])
        self.assertEqual(self.close(millis(19)).status_code, 409)

    def test_invalid_times_and_missing(self):
        self.assertEqual(self.close(millis(19)).status_code, 404)
        self.punch()
        self.assertEqual(self.close(millis(9, 30)).status_code, 422)
        self.assertEqual(self.close(millis(9, 30, 1, day=7)).status_code, 422)
        self.assertEqual(self.close(millis(9, 30, day=7)).status_code, 200)
        self.assertEqual(self.correct(punch_out=millis(9, 30)).status_code, 422)
        self.assertEqual(self.correct(punch_in=millis(9, 30, day=7)).status_code, 422)
        self.assertEqual(self.correct(status=None).status_code, 422)
        self.assertEqual(self.correct().status_code, 422)
        self.assertEqual(self.api.patch('/attendance/EMP0001/bad', json={
            'reason': 'Fix date', 'regularized_by': 'HR'}).status_code, 422)

    def test_correction_history_and_transitions(self):
        self.punch(millis(10, 5))
        self.close(millis(18, 30))
        changed = self.correct(punch_in=millis(9, 28) + 900)
        self.assertEqual(changed.status_code, 200)
        data = changed.json()
        self.assertEqual(data['late_minutes'], 0)
        self.assertEqual(data['work_hours'], 9.03)
        entry = data['history'][0]
        self.assertEqual(set(entry['changes']), {'punch_in', 'late_minutes', 'work_hours'})
        self.assertEqual(entry['changes']['punch_in']['to'], millis(9, 28))
        self.assertEqual(self.correct(status='LEAVE', punch_in=millis(9)).status_code, 422)
        leave = self.correct(status='LEAVE').json()
        self.assertIsNone(leave['punch_in'])
        self.assertIsNone(leave['punch_out'])
        self.assertEqual(len(leave['history']), 2)
        self.assertEqual(self.correct(status='PRESENT').status_code, 422)
        restored = self.correct(status='WFH', punch_in=millis(9, 30), punch_out=millis(13)).json()
        self.assertTrue(restored['half_day'])
        self.assertEqual(len(restored['history']), 3)

    def test_overnight(self):
        m.db.employees.update_one({'emp_code': 'EMP0001'}, {'$set': {'shift_start': '22:00', 'shift_end': '06:00'}})
        self.punch(millis(21, 55))
        response = self.close(millis(6, 40, day=7))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['date'], '2026-07-06')
        self.assertEqual(response.json()['overtime_minutes'], 40)

    def test_latest_closed_record_does_not_close_older_open(self):
        self.punch()
        self.punch(millis(9, 30, day=7))
        self.close(millis(18, 30, day=7))
        self.assertEqual(self.close(millis(19, day=7)).status_code, 409)
        self.assertIsNone(m.db.attendance_logs.find_one({'date': '2026-07-06'})['punch_out'])

    def test_concurrent_close_and_corrections(self):
        self.punch()
        # Force both writers to read the same snapshot before either updates it.
        original = m.snapshot_filter
        barrier = Barrier(2)
        def synchronized(record):
            query = original(record)
            barrier.wait(timeout=10)
            return query
        with patch.object(m, 'snapshot_filter', synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: self.close(millis(18, 30)).status_code, range(2)))
        self.assertEqual(sorted(codes), [200, 409])
        with patch.object(m, 'snapshot_filter', synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda status: self.correct(status=status).status_code, ['WFH', 'ON_DUTY']))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(len(m.db.attendance_logs.find_one({})['history']), 1)

    def test_legacy_correction_and_ignored_derived_input(self):
        self.punch()
        m.db.attendance_logs.update_one({}, {'$unset': {'history': '', 'half_day': ''}})
        response = self.correct(status='WFH', work_hours=999)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['work_hours'])
        self.assertFalse(response.json()['half_day'])
        self.assertEqual(set(response.json()['history'][0]['changes']), {'status'})
