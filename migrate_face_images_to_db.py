"""
Script لنقل صور الوجوه من الملفات إلى قاعدة البيانات
يُشغَّل مرة واحدة لحفظ الصور الموجودة قبل deployment
"""

import os
import base64
from database import get_db_connection, IS_POSTGRES

def migrate_face_images():
    """نقل جميع صور الوجوه من الملفات إلى قاعدة البيانات"""
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # التحقق من وجود عمود face_image_data
        if IS_POSTGRES:
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='students' AND column_name='face_image_data'
            """)
            has_column = cursor.fetchone() is not None
        else:
            cursor.execute('PRAGMA table_info(students)')
            columns = {row['name'] for row in cursor.fetchall()}
            has_column = 'face_image_data' in columns
        
        if not has_column:
            print('[Migration] ❌ عمود face_image_data غير موجود!')
            print('[Migration] شغّل init_face_recognition_tables() أولاً')
            return
        
        # جلب الطلاب المسجلين بصور وجه
        if IS_POSTGRES:
            cursor.execute("""
                SELECT id, full_name, face_image_path, face_image_data
                FROM students
                WHERE face_enrolled = TRUE 
                  AND face_image_path IS NOT NULL
            """)
        else:
            cursor.execute("""
                SELECT id, full_name, face_image_path, face_image_data
                FROM students
                WHERE face_enrolled = 1 
                  AND face_image_path IS NOT NULL
            """)
        
        students = cursor.fetchall()
        print(f'\n[Migration] وجدنا {len(students)} طالب مسجل بوجه')
        
        migrated = 0
        skipped = 0
        failed = 0
        
        for student in students:
            student_id = student['id']
            full_name = student['full_name']
            face_path = student['face_image_path']
            has_data = student.get('face_image_data')
            
            # إذا الصورة موجودة مسبقاً في DB
            if has_data:
                print(f'  ⏭️  {full_name}: الصورة موجودة مسبقاً في DB')
                skipped += 1
                continue
            
            # محاولة قراءة الصورة من الملف
            candidates = [
                face_path,
                os.path.join(BASE_DIR, face_path.lstrip('/')),
                os.path.join(BASE_DIR, 'instance', face_path.lstrip('/')),
                os.path.join(BASE_DIR, 'static', face_path.lstrip('/static/').lstrip('/')),
            ]
            
            image_found = False
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    try:
                        with open(candidate, 'rb') as f:
                            image_bytes = f.read()
                            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                        
                        # حفظ في DB
                        if IS_POSTGRES:
                            cursor.execute("""
                                UPDATE students 
                                SET face_image_data = %s
                                WHERE id = %s
                            """, (image_b64, student_id))
                        else:
                            cursor.execute("""
                                UPDATE students 
                                SET face_image_data = ?
                                WHERE id = ?
                            """, (image_b64, student_id))
                        
                        print(f'  ✅ {full_name}: نُقلت الصورة إلى DB ({len(image_b64)} حرف)')
                        migrated += 1
                        image_found = True
                        break
                        
                    except Exception as e:
                        print(f'  ❌ {full_name}: فشل قراءة الصورة - {e}')
                        failed += 1
                        break
            
            if not image_found:
                print(f'  ⚠️  {full_name}: لم نجد الصورة في الملفات')
                failed += 1
        
        conn.commit()
        
        print(f'\n[Migration] ═══════════════════════════════════════')
        print(f'[Migration] ✅ نُقل: {migrated}')
        print(f'[Migration] ⏭️  موجود مسبقاً: {skipped}')
        print(f'[Migration] ❌ فشل: {failed}')
        print(f'[Migration] ═══════════════════════════════════════')
        
    except Exception as e:
        print(f'[Migration Error] {e}')
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    print('[Migration] بدء نقل صور الوجوه من الملفات إلى قاعدة البيانات...\n')
    migrate_face_images()
    print('\n[Migration] انتهى!')
