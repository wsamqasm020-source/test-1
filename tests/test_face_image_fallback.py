import os
import tempfile
import unittest
from unittest.mock import patch

import face_recognition_utils
from app import app as attendance_app


class FaceImageFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = attendance_app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'admin'

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_face_file_uses_profile_image(self):
        profile_image = '/static/uploads/profiles/profile.jpg'
        profile_path = os.path.join(
            self.temp_dir.name, 'static', 'uploads', 'profiles', 'profile.jpg'
        )
        os.makedirs(os.path.dirname(profile_path))
        with open(profile_path, 'wb') as image:
            image.write(b'profile image')

        student = {
            'id': 322,
            'full_name': 'Test Student',
            'student_code': 'TEST322',
            'department': 'Test',
            'teacher_name': 'First',
            'group_name': 'Morning',
            'face_enrolled': 1,
            'face_image_path': '/static/uploads/faces/face_322.jpg',
            'profile_image': profile_image,
        }

        with patch.object(attendance_app, 'root_path', self.temp_dir.name), \
                patch('app.get_student_by_id', return_value=student), \
                patch.object(face_recognition_utils, 'get_face_image_path', return_value=None), \
        patch('database.get_all_students', return_value=[student]):
            image_response = self.client.get('/api/face/image/322')
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response.mimetype, 'image/jpeg')
            self.assertEqual(image_response.data, b'profile image')
            image_response.close()

            students_response = self.client.get('/api/face/enrolled-students')
            self.assertEqual(students_response.status_code, 200)
            listed_student = students_response.get_json()['students'][0]
            self.assertEqual(listed_student['face_image_path'], profile_image)
