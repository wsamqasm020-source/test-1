"""تشغيل face recognition migrations"""
from database import init_face_recognition_tables

print('[Migration] تشغيل init_face_recognition_tables...')
init_face_recognition_tables()
print('[Migration] انتهى!')
