"""فحص حالة الطلاب المسجلين"""
from database import get_all_students

students = get_all_students()
print(f'\nعدد الطلاب الكلي: {len(students)}\n')

for s in students:
    enrolled = s.get('face_enrolled')
    path = s.get('face_image_path')
    data = s.get('face_image_data')
    
    print(f"📋 {s['full_name']}")
    print(f"   - face_enrolled: {enrolled}")
    print(f"   - face_image_path: {path}")
    print(f"   - face_image_data: {'موجود' if data else 'فارغ'}")
    print()
