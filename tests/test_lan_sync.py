import datetime
import base64
import io
import os
import subprocess
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

import database
import lan_sync
from lan_sync import lan_sync_blueprint


class LanSyncTests(unittest.TestCase):
    def setUp(self):
        if database.IS_POSTGRES:
            self.skipTest('LAN sync tests require SQLite')
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = database.DATABASE
        self.original_snapshot_time = lan_sync._last_snapshot_at
        database.DATABASE = os.path.join(self.temp_dir.name, 'local.sqlite')
        lan_sync._last_snapshot_at = 0
        database.init_database()

    def tearDown(self):
        database.DATABASE = self.original_database
        lan_sync._last_snapshot_at = self.original_snapshot_time
        self.temp_dir.cleanup()

    def add_test_records(self, student_code='LANSTUDENT01'):
        student_id = database.add_student(
            'LAN Test Student', 'test', 'first', 'morning',
            student_code, f'CODE:{student_code}'
        )
        subject_id = database.add_subject(
            'LAN Test Subject', 'ignored', 'test', 'first', 'first', 'morning'
        )
        subject = next(item for item in database.get_all_subjects() if item['id'] == subject_id)
        return student_id, subject

    def make_sync_client(self):
        app = Flask('lan-sync-test')
        app.register_blueprint(lan_sync_blueprint)
        app.testing = True
        return app.test_client()

    def test_cloud_replay_is_authenticated_and_idempotent(self):
        student_id, subject = self.add_test_records()
        event = {
            'event_id': str(uuid.uuid4()),
            'student_code': 'LANSTUDENT01',
            'subject_code': subject['code'],
            'scanned_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        client = self.make_sync_client()

        with patch.dict(os.environ, {'LAN_SYNC_TOKEN': 'test-token'}):
            self.assertEqual(client.get('/api/lan-sync/snapshot').status_code, 403)
            headers = {'X-LAN-SYNC-TOKEN': 'test-token'}
            first = client.post('/api/lan-sync/attendance', headers=headers, json={'events': [event]})
            second = client.post('/api/lan-sync/attendance', headers=headers, json={'events': [event]})

        self.assertTrue(first.get_json()['results'][0]['success'])
        self.assertTrue(second.get_json()['results'][0]['already_synced'])
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_local_outbox_preserves_wall_clock_time(self):
        student_id, subject = self.add_test_records()
        local_scan = datetime.datetime(
            2026, 5, 4, 0, 15,
            tzinfo=datetime.timezone(datetime.timedelta(hours=3))
        )
        event_id = str(uuid.uuid4())
        self.assertTrue(database.record_attendance(
            student_id, subject['id'], 'morning', local_scan, event_id
        ))

        event = database.get_pending_lan_attendance()[0]
        synced_time = datetime.datetime.fromisoformat(event['scanned_at'])
        self.assertEqual(synced_time.date(), datetime.date(2026, 5, 4))
        self.assertEqual(synced_time.hour, 0)
        self.assertIsNotNone(synced_time.utcoffset())
        self.assertTrue(database.mark_lan_attendance_synced(event_id))
        self.assertEqual(database.get_pending_lan_attendance(), [])

    def test_student_qr_scan_records_local_attendance_once(self):
        from app import app as attendance_app

        student_id, subject = self.add_test_records()
        qr_session = database.create_subject_qr_session(subject['id'], duration_minutes=30)
        event_id = str(uuid.uuid4())
        qr_data = f"SUBJECT:{subject['id']}|SESSION:{qr_session['token']}"
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = student_id

        first = client.post('/student/api/scan-attendance', json={
            'qr_data': qr_data,
            'event_id': event_id
        })
        replay = client.post('/student/api/scan-attendance', json={
            'qr_data': qr_data,
            'event_id': event_id
        })

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()['success'])
        self.assertTrue(replay.get_json()['already_synced'])
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_offline_student_qr_scan_accepts_utc_timestamp(self):
        from app import app as attendance_app

        student_id, subject = self.add_test_records()
        qr_session = database.create_subject_qr_session(subject['id'], duration_minutes=30)
        event_id = str(uuid.uuid4())
        qr_data = f"SUBJECT:{subject['id']}|SESSION:{qr_session['token']}"
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = student_id

        response = client.post('/student/api/scan-attendance', json={
            'qr_data': qr_data,
            'event_id': event_id,
            'offline_sync': True,
            'scanned_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_attendance_status_includes_present_student_outside_subject_grade(self):
        student_id, subject = self.add_test_records()
        conn = database.get_db_connection()
        conn.execute('UPDATE students SET teacher_name = ? WHERE id = ?', ('الثالثة', student_id))
        conn.commit()
        conn.close()
        database.record_attendance(
            student_id, subject['id'], 'morning', datetime.datetime.now()
        )

        records = database.get_students_attendance_status(
            subject['id'], datetime.date.today().isoformat()
        )

        present_record = next(record for record in records if record['id'] == student_id)
        self.assertTrue(present_record['is_present'])

    def test_attendance_report_returns_present_and_absent_for_selected_stage(self):
        from app import app as attendance_app

        present_id, subject = self.add_test_records()
        absent_id = database.add_student(
            'Absent Stage Student', 'test', 'الثالثة', 'morning',
            'LANSTUDENT02', 'CODE:LANSTUDENT02'
        )
        conn = database.get_db_connection()
        conn.execute('UPDATE students SET teacher_name = ? WHERE id = ?', ('الثالثة', present_id))
        conn.commit()
        conn.close()
        database.record_attendance(
            present_id, subject['id'], 'morning', datetime.datetime.now()
        )

        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'
        response = client.get(
            f"/api/attendance/{subject['id']}?date={datetime.date.today().isoformat()}&stage=الثالثة"
        )

        self.assertEqual(response.status_code, 200)
        records = {record['id']: record for record in response.get_json()['attendance']}
        self.assertTrue(records[present_id]['is_present'])
        self.assertFalse(records[absent_id]['is_present'])

    def test_teacher_generates_subject_qr_on_local_server(self):
        from app import app as attendance_app

        _, subject = self.add_test_records()
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'

        response = client.post('/api/generate-qr', json={
            'qr_mode': 'subject',
            'subject_id': subject['id']
        })
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertTrue(data['qr_code'].startswith('data:image/png;base64,'))
        self.assertEqual(data['subject']['id'], subject['id'])
        self.assertTrue(database.verify_subject_qr_session(subject['id'], data['session_token']))

    def test_snapshot_merge_remaps_ids_and_deduplicates(self):
        student_id, subject = self.add_test_records()
        event_id = str(uuid.uuid4())
        database.record_attendance(
            student_id, subject['id'], 'morning', datetime.datetime.now(), event_id
        )
        conn = database.get_db_connection()
        conn.execute('UPDATE attendance_sync_events SET cloud_synced = 1 WHERE event_id = ?', (event_id,))
        conn.commit()
        conn.close()
        snapshot = database.export_lan_sync_snapshot()

        local_path = os.path.join(self.temp_dir.name, 'mirror.sqlite')
        database.DATABASE = local_path
        database.init_database()
        database.add_student('ID collision', 'test', 'first', 'morning', 'LOCALSTUDENT01', 'CODE:LOCALSTUDENT01')
        database.add_subject('ID collision', 'ignored', 'test', 'test', 'first', 'morning')

        database.apply_lan_sync_snapshot(snapshot)
        database.apply_lan_sync_snapshot(snapshot)

        local_student = database.get_student_by_code('LANSTUDENT01')
        local_subject = next(item for item in database.get_all_subjects() if item['code'] == subject['code'])
        self.assertIsNotNone(local_student)
        self.assertEqual(len(database.get_attendance_by_student(local_student['id'])), 1)
        self.assertEqual(len(database.get_all_students()), 2)
        self.assertEqual(len(database.get_all_subjects()), 2)
        self.assertEqual(database.get_pending_lan_attendance(), [])

    def test_local_worker_marks_only_cloud_accepted_events(self):
        student_id, subject = self.add_test_records()
        event_id = str(uuid.uuid4())
        database.record_attendance(
            student_id, subject['id'], 'morning', datetime.datetime.now(), event_id
        )
        calls = []

        def fake_request(path, payload=None):
            calls.append(path)
            if path == 'snapshot':
                return {'success': True, 'snapshot': {}}
            return {'results': [{'event_id': event_id, 'success': True}]}

        with patch.dict(os.environ, {
            'LAN_SYNC_URL': 'https://cloud.example/api/lan-sync',
            'LAN_SYNC_TOKEN': 'test-token'
        }), patch.object(lan_sync, '_remote_request', side_effect=fake_request):
            result = lan_sync.sync_lan_data_once()

        self.assertEqual(calls, ['snapshot', 'attendance'])
        self.assertEqual(result['synced_events'], 1)
        self.assertEqual(database.get_pending_lan_attendance(), [])

    def test_remote_sync_refuses_plain_http(self):
        with patch.dict(os.environ, {
            'LAN_SYNC_URL': 'http://cloud.example/api/lan-sync',
            'LAN_SYNC_TOKEN': 'test-token'
        }):
            with self.assertRaisesRegex(RuntimeError, 'HTTPS'):
                lan_sync._remote_request('snapshot')

    def test_network_page_advertises_the_actual_listener_port(self):
        with patch('threading.Thread.start'):
            from app import app as attendance_app

        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'

        fake_socket = SimpleNamespace(
            connect=lambda _address: None,
            getsockname=lambda: ('192.168.137.1', 0),
            close=lambda: None
        )
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='Started')):
            with patch('socket.socket', return_value=fake_socket):
                response = client.get(
                    '/api/network-info',
                    environ_overrides={'SERVER_PORT': '5150'}
                )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['server_port'], '5150')
        self.assertEqual(data['student_url'], 'http://192.168.137.1:5150')
        self.assertEqual(data['teacher_url'], 'http://192.168.137.1:5150')

    def test_student_qr_rejects_missing_or_invalid_session_token(self):
        student_id, subject = self.add_test_records()
        from app import app as attendance_app
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = student_id

        missing_token = client.post('/student/api/scan-attendance', json={
            'qr_data': f'SUBJECT:{subject["id"]}'
        })
        invalid_token = client.post('/student/api/scan-attendance', json={
            'qr_data': f'SUBJECT:{subject["id"]}|SESSION:{"0" * 32}'
        })

        self.assertEqual(missing_token.status_code, 400)
        self.assertEqual(invalid_token.status_code, 403)
        self.assertEqual(database.get_attendance_by_student(student_id), [])

    def test_teacher_subject_qr_requires_current_session(self):
        student_id, subject = self.add_test_records()
        from app import app as attendance_app
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'

        rejected = client.post('/api/scan-qr', json={
            'qr_data': f'SUBJECT:{subject["id"]}|SESSION:{"0" * 32}',
            'subject_id': subject['id']
        })
        qr_session = database.create_subject_qr_session(subject['id'])
        accepted = client.post('/api/scan-qr', json={
            'qr_data': f'SUBJECT:{subject["id"]}|SESSION:{qr_session["token"]}',
            'subject_id': subject['id']
        })

        self.assertEqual(rejected.status_code, 403)
        self.assertTrue(accepted.get_json()['success'])
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_face_image_is_private_and_requires_teacher_login(self):
        import face_recognition_utils
        from PIL import Image
        from app import app as attendance_app

        student_id, _ = self.add_test_records()
        database.init_face_recognition_tables()
        image = Image.new('RGB', (80, 80), color=(120, 100, 80))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()

        with tempfile.TemporaryDirectory() as image_dir:
            with patch.object(face_recognition_utils, '_FACES_DIR', image_dir):
                stored_path = face_recognition_utils.save_face_image(data, student_id)
                self.assertTrue(stored_path.startswith('face-images/'))
                conn = database.get_db_connection()
                conn.execute(
                    'UPDATE students SET face_image_path = ? WHERE id = ?',
                    (stored_path, student_id)
                )
                conn.commit()
                conn.close()

                client = attendance_app.test_client()
                public_response = client.get(f'/static/uploads/faces/face_{student_id}.jpg')
                self.assertEqual(public_response.status_code, 404)

                with client.session_transaction() as session:
                    session['user_id'] = 1
                    session['username'] = 'admin'
                private_response = client.get(f'/api/face/image/{student_id}')

                self.assertEqual(private_response.status_code, 200)
                self.assertEqual(private_response.mimetype, 'image/jpeg')
                self.assertEqual(private_response.headers['Cache-Control'], 'private, no-store')
                private_response.close()

    def test_face_recognition_rejects_multiple_faces(self):
        import face_recognition_utils
        from PIL import Image

        image = Image.new('RGB', (80, 80), color=(120, 100, 80))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        image_data = base64.b64encode(buffer.getvalue()).decode()
        deepface = SimpleNamespace(
            extract_faces=lambda **_kwargs: [{}, {}],
            represent=lambda **_kwargs: self.fail('embedding must not run for multiple faces')
        )

        with patch.object(face_recognition_utils, '_DEEPFACE_AVAILABLE', True), \
                patch.object(face_recognition_utils, '_DeepFace', deepface, create=True), \
                patch.object(face_recognition_utils, '_quality_check', return_value=(True, 'جيد')):
            result = face_recognition_utils.FaceRecognitionManager.recognize_face(
                image_data, [{'student_id': 1, 'face_encoding': ''}]
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['result'], 'MULTIPLE_FACES')

    def test_face_recognition_accepts_single_retinaface_detection_and_limits_embedding(self):
        import face_recognition_utils
        import numpy as np
        from PIL import Image

        image = Image.new('RGB', (80, 80), color=(120, 100, 80))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        image_data = base64.b64encode(buffer.getvalue()).decode()
        encoding = base64.b64encode(
            np.asarray([0.1] * 512, dtype=np.float32).tobytes()
        ).decode()
        calls = {}

        def extract_faces(**kwargs):
            calls['detection'] = kwargs
            return [{'facial_area': {'x': 5, 'y': 7, 'w': 40, 'h': 35}}]

        def represent(**kwargs):
            calls.setdefault('embedding', []).append(kwargs)
            if kwargs['detector_backend'] == 'opencv':
                raise ValueError('Face could not be detected in numpy array')
            return [{'embedding': [0.1] * 512}]

        deepface = SimpleNamespace(extract_faces=extract_faces, represent=represent)
        with patch.object(face_recognition_utils, '_DEEPFACE_AVAILABLE', True), \
                patch.object(face_recognition_utils, '_DeepFace', deepface, create=True), \
                patch.object(face_recognition_utils, '_quality_check', return_value=(True, 'جيد')):
            result = face_recognition_utils.FaceRecognitionManager.recognize_face(
                image_data, [{'student_id': 1, 'face_encoding': encoding}]
            )

        self.assertTrue(result['success'])
        self.assertEqual(calls['detection']['detector_backend'], 'retinaface')
        self.assertEqual(
            [call['detector_backend'] for call in calls['embedding']],
            ['opencv', 'skip']
        )
        self.assertEqual(calls['embedding'][1]['max_faces'], 1)
        self.assertEqual(calls['embedding'][1]['img_path'].shape[:2], (35, 40))

    def test_face_attendance_requires_matching_active_session_and_deduplicates(self):
        from app import app as attendance_app

        student_id, subject = self.add_test_records()
        database.init_face_recognition_tables()
        face_session_id = database.create_face_attendance_session(
            subject['id'], created_by=1, threshold=0.75
        )
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'

        with patch('database.get_all_enrolled_faces', return_value=[{
            'student_id': student_id,
            'name': 'LAN Test Student',
            'face_encoding': 'placeholder'
        }]), patch(
            'face_recognition_utils.FaceRecognitionManager.recognize_face',
            return_value={
                'success': True,
                'result': 'SUCCESS',
                'student_id': student_id,
                'confidence': 0.9
            }
        ):
            no_session = client.post('/api/face/recognize', json={
                'image_data': 'data:image/jpeg;base64,ZmFrZQ==',
                'subject_id': subject['id']
            })
            mismatched_session = client.post('/api/face/recognize', json={
                'image_data': 'data:image/jpeg;base64,ZmFrZQ==',
                'subject_id': subject['id'] + 1,
                'session_id': face_session_id
            })
            accepted = client.post('/api/face/recognize', json={
                'image_data': 'data:image/jpeg;base64,ZmFrZQ==',
                'subject_id': subject['id'],
                'session_id': face_session_id
            })
            duplicate = client.post('/api/face/recognize', json={
                'image_data': 'data:image/jpeg;base64,ZmFrZQ==',
                'subject_id': subject['id'],
                'session_id': face_session_id
            })

        self.assertEqual(no_session.status_code, 400)
        self.assertEqual(mismatched_session.status_code, 409)
        self.assertTrue(accepted.get_json()['success'], accepted.get_json())
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_attendance_race_records_a_student_once(self):
        student_id, subject = self.add_test_records()
        barrier = threading.Barrier(2)
        results = []

        def record():
            barrier.wait()
            results.append(database.record_attendance(
                student_id, subject['id'], 'morning', datetime.datetime.now()
            ))

        workers = [threading.Thread(target=record) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertCountEqual(results, [True, False])
        self.assertEqual(len(database.get_attendance_by_student(student_id)), 1)

    def test_student_grades_require_its_unexpired_access_code(self):
        student_id, subject = self.add_test_records()
        database.add_grade(student_id, subject['id'], 85)
        from app import app as attendance_app
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = student_id

        fake_code = client.post('/student/api/grades', json={'code': '123456'})
        active_code = database.generate_access_code(student_id)
        valid_code = client.post('/student/api/grades', json={'code': active_code})

        self.assertEqual(fake_code.status_code, 400)
        self.assertTrue(valid_code.get_json()['success'])
        self.assertEqual(len(valid_code.get_json()['grades']), 1)

    def test_student_without_password_cannot_authenticate(self):
        student_id, _ = self.add_test_records()
        student = database.get_student_by_id(student_id)
        from app import app as attendance_app
        client = attendance_app.test_client()

        response = client.post('/student/login', data={
            'student_code': student['student_code'],
            'password': 'arbitrary-password'
        })

        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as session:
            self.assertNotIn('student_id', session)
            self.assertIn('لم يتم تعيين كلمة مرور', session['login_error'])

    def test_profile_upload_reencodes_image_and_ignores_client_filename(self):
        from PIL import Image
        from app import app as attendance_app

        student_id, _ = self.add_test_records()
        image = Image.new('RGB', (80, 80), color=(120, 100, 80))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        client = attendance_app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = student_id

        response = client.post('/student/update-profile', data={
            'profile_image': (buffer, '../../profile.html')
        }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 302)
        saved_student = database.get_student_by_id(student_id)
        relative_path = saved_student['profile_image'].lstrip('/').replace('/', os.sep)
        saved_path = os.path.join(
            os.path.dirname(database.__file__),
            relative_path
        )
        try:
            self.assertTrue(saved_student['profile_image'].startswith('/static/uploads/profiles/student_'))
            self.assertTrue(saved_student['profile_image'].endswith('.jpg'))
            self.assertTrue(os.path.isfile(saved_path))
        finally:
            if os.path.isfile(saved_path):
                os.remove(saved_path)


if __name__ == '__main__':
    unittest.main()
