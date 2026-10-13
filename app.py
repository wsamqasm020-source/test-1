"""
تطبيق تسجيل الحضور بالـ QR
Flask Web Application
"""
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, g, render_template, request, jsonify, send_file, redirect, url_for, flash, session, send_from_directory, Response, stream_with_context
from functools import wraps
import json
import queue as _queue_module
import qrcode
import io
import base64
import os
import hashlib
from datetime import datetime, timedelta, timezone
from database import (
    init_database, add_student, get_student_by_code, get_student_by_id,
    get_all_students, add_subject, get_all_subjects, get_subjects_by_department,
    record_attendance, record_attendance_for_subject, get_attendance_by_subject, get_attendance_by_student,
    get_today_attendance_stats, delete_student, delete_subject,
    get_student_group_name, get_last_attendance_time, verify_user, change_user_password,
    get_settings, save_settings, get_all_users, add_new_user, delete_user_by_username,
    get_students_attendance_status, get_subject_latest_attendance_date, get_subject_latest_attendance_date_before,
    get_attendance_count_by_subject_date, attendance_sync_event_exists,
    verify_subject_qr_session_at, get_client_mutation_result, save_client_mutation_result,
    # Face Recognition functions
    init_face_recognition_tables, update_student_face_encoding, get_student_face_encoding,
    get_all_enrolled_faces, delete_student_face_data, log_face_recognition_attempt,
    create_face_attendance_session, close_face_attendance_session, get_active_face_session,
    record_face_attendance, get_face_recognition_logs, get_face_attendance_stats,
    get_students_without_face_enrollment, get_face_recognition_settings, save_face_recognition_settings
)
from lan_sync import lan_sync_blueprint, start_lan_sync_worker


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024


@app.before_request
def block_public_face_images():
    if request.path.startswith('/static/uploads/faces/'):
        return '', 404


def _load_or_create_secret_key():
    """مفتاح الجلسات: من env أو ملف محفوظ حتى لا تنكسر الجلسات عند إعادة التشغيل"""
    key = os.environ.get('FLASK_SECRET_KEY')
    if key:
        return key
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')
    try:
        if os.path.exists(key_file):
            with open(key_file, 'r', encoding='utf-8') as f:
                saved = f.read().strip()
                if saved:
                    return saved
        key = os.urandom(32).hex()
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(key)
        return key
    except OSError:
        return os.urandom(32)

app.secret_key = _load_or_create_secret_key()
app.register_blueprint(lan_sync_blueprint)


@app.before_request
def replay_client_mutation():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE') or not request.path.startswith('/api/'):
        return None

    request_id = request.headers.get('X-Client-Request-ID', '').strip()
    if not request_id or len(request_id) > 128:
        return None

    try:
        stored = get_client_mutation_result(request_id)
    except Exception as error:
        print(f'[Offline Sync] Idempotency lookup unavailable: {error}')
        return None

    if stored:
        return app.response_class(
            stored['response_body'],
            status=stored['status_code'],
            content_type=stored['content_type']
        )

    g.client_mutation_request_id = request_id
    return None


@app.after_request
def store_client_mutation_result(response):
    request_id = getattr(g, 'client_mutation_request_id', None)
    if request_id and 200 <= response.status_code < 300 and response.is_json:
        try:
            save_client_mutation_result(
                request_id,
                response.status_code,
                response.headers.get('Content-Type', 'application/json'),
                response.get_data(as_text=True)
            )
        except Exception as error:
            print(f'[Offline Sync] Idempotency result could not be saved: {error}')

    # CORS للشبكة المحلية فقط — يسمح للهواتف المتصلة بالراوتر نفسه
    origin = request.headers.get('Origin', '')
    if (origin.startswith('http://192.168.')
            or origin.startswith('https://192.168.')
            or origin.startswith('http://10.')
            or origin.startswith('https://10.')
            or origin.startswith('http://172.')
            or origin.startswith('https://172.')
            or 'localhost' in origin
            or origin == ''):
        allow_origin = origin if origin else '*'
        response.headers['Access-Control-Allow-Origin'] = allow_origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Client-Request-ID'
        response.headers['Access-Control-Allow-Credentials'] = 'true'

    return response

# ✅ إبقاء الجلسة لمدة 7 أيام
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_PERMANENT'] = True

# ✅ تهيئة قاعدة البيانات - تشغيل في background بعد بدء الـ server
import threading

def initialize_app():
    try:
        with app.app_context():
            init_database()
            print('[App] ✅ Database initialized successfully')
            
            # تهيئة جداول Face Recognition
            try:
                init_face_recognition_tables()
                print('[App] ✅ Face Recognition tables initialized')
            except Exception as e:
                print(f'[App] ⚠️  Face Recognition init warning: {e}')
            
            try:
                from database import cleanup_expired_qr_sessions
                deleted = cleanup_expired_qr_sessions()
                if deleted > 0:
                    print(f'[Cleanup] تم حذف {deleted} جلسة QR منتهية')
            except Exception as e:
                print(f'[Cleanup Error] {e}')
            if start_lan_sync_worker():
                print('[LAN Sync] Local attendance cloud replay enabled')
    except Exception as e:
        print(f'[App] ❌ Database init error: {e}')

# ✅ تشغيل init بشكل متزامن قبل استقبال أي طلب
# (تشغيله في thread يسبب سباقاً: أول طلب يصل قبل إنشاء الجداults → Internal Server Error 500)
initialize_app()

# فترة المنع بين تسجيلات الحضور (بالدقائق)
COOLDOWN_MINUTES = 15


def login_required(f):
    """ديكوريتور للتحقق من تسجيل الدخول"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # مسح أي رسائل قديمة لتجنب التكرار
            session.pop('_flashes', None)
            flash('يرجى تسجيل الدخول أولاً', 'error')
            return redirect(url_for('teacher_login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """ديكوريتور للتحقق من أن المستخدم هو الـ admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('username') != 'admin':
            flash('هذه الصفحة متاحة فقط للمدير', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def generate_qr_code(data):
    """توليد QR code من البيانات - دالة موحدة"""
    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    return qr.make_image(fill_color="black", back_color="white")


def qr_to_base64(img):
    """تحويل صورة QR إلى base64"""
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


def generate_student_code(department, teacher_name, group_name):
    """توليد رقم طالب فريد"""
    dept_prefix = department[:2].upper() if department else 'XX'
    teacher_prefix = teacher_name[:2].upper() if teacher_name else 'XX'
    group_prefix = group_name[:2].upper() if group_name else 'XX'
    
    prefix = f"{dept_prefix}{teacher_prefix}{group_prefix}"
    
    students = get_all_students()
    max_num = 0
    for student in students:
        if student['student_code'].startswith(prefix):
            try:
                num = int(student['student_code'][-3:])
                max_num = max(max_num, num)
            except:
                pass
    
    new_num = max_num + 1
    return f"{prefix}{new_num:03d}"


def check_attendance_cooldown(student_id):
    """التحقق من فترة المنع بين تسجيلات الحضور"""
    last_attendance = get_last_attendance_time(student_id)
    
    if not last_attendance:
        return True, 0
    
    current_time = datetime.now()
    elapsed_seconds = (current_time - last_attendance).total_seconds()
    cooldown_seconds = COOLDOWN_MINUTES * 60
    
    if elapsed_seconds < cooldown_seconds:
        remaining_seconds = int(cooldown_seconds - elapsed_seconds)
        return False, remaining_seconds
    
    return True, 0


def format_remaining_time(seconds):
    """تنسيق الوقت المتبقي بالدقائق والثواني"""
    minutes = seconds // 60
    secs = seconds % 60
    if minutes > 0:
        return f"{minutes} دقيقة و {secs} ثانية"
    return f"{secs} ثانية"


def parse_attendance_scan_time(data):
    event_id = str(data.get('event_id') or '').strip()
    if event_id:
        import uuid
        try:
            event_id = str(uuid.UUID(event_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError('معرّف مزامنة غير صالح') from exc

    if not data.get('offline_sync'):
        return event_id or None, datetime.now()
    if not event_id:
        raise ValueError('معرّف المزامنة مطلوب')

    scanned_at_value = data.get('scanned_at')
    try:
        scanned_at = datetime.fromisoformat(str(scanned_at_value).replace('Z', '+00:00'))
    except (TypeError, ValueError) as exc:
        raise ValueError('وقت المسح غير صالح') from exc

    now = datetime.now()
    utc_scanned_at = scanned_at.astimezone(timezone.utc).replace(tzinfo=None) if scanned_at.tzinfo else scanned_at
    if utc_scanned_at < now - timedelta(days=7) or utc_scanned_at > now + timedelta(minutes=5):
        raise ValueError('انتهت صلاحية سجل الحضور غير المتصل')
    return event_id, scanned_at


def parse_subject_qr(qr_data):
    import re

    match = re.match(r'^SUBJECT:(\d+)\|SESSION:([a-f0-9]{32})(?:\||$)', qr_data)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def save_uploaded_image(upload, upload_dir, filename_prefix):
    from PIL import Image, UnidentifiedImageError
    import uuid

    raw = upload.stream.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError('يجب أن يكون حجم الصورة أقل من 5 ميغابايت')

    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('صيغة الصورة غير مدعومة')
            width, height = image.size
            if width < 1 or height < 1 or width * height > 16_000_000:
                raise ValueError('أبعاد الصورة غير صالحة')
            image.load()
            normalized = image.convert('RGB')
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ValueError('الملف المحدد ليس صورة صالحة') from error

    output = io.BytesIO()
    normalized.save(output, format='JPEG', quality=88, optimize=True)
    filename = f'{filename_prefix}_{uuid.uuid4().hex}.jpg'
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    temporary_path = f'{filepath}.tmp'
    try:
        with open(temporary_path, 'xb') as saved_file:
            saved_file.write(output.getvalue())
        os.replace(temporary_path, filepath)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return filename


# ============================================
# 🔥 ROUTE مهم جداً للـ Service Worker
# ============================================

@app.route('/health')
def health_check():
    """Health check endpoint for Docker and deployment platforms"""
    try:
        # فحص قاعدة البيانات
        from database import get_all_students
        students_count = len(get_all_students())
        
        # فحص Face Recognition
        face_ready = False
        try:
            import face_recognition_utils as _fr
            face_ready = bool(getattr(_fr, '_DEEPFACE_AVAILABLE', False))
        except Exception:
            pass
        
        return jsonify({
            'status': 'healthy',
            'message': 'Application is running',
            'database': 'connected',
            'students_count': students_count,
            'face_recognition': 'ready' if face_ready else 'not_installed',
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }), 503


@app.route('/sw.js')
def service_worker():
    """تقديم Service Worker"""
    response = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/offline.html')
def offline_page():
    """صفحة Offline"""
    return send_from_directory('static', 'offline.html')


# ============================================
# Routes تسجيل الدخول (بدون حماية)
# ============================================

@app.route('/')
def unified_index():
    """الصفحة الرئيسية الموحدة"""
    # إذا المستخدم مسجل دخول كمدرس
    if 'user_id' in session:
        return redirect(url_for('index'))
    # إذا المستخدم مسجل دخول كطالب
    elif 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    
    # جلب شعار النظام من الإعدادات (نفس صورة القسم)
    settings_data = get_settings()
    logo_path = settings_data.get('dept_image') or settings_data.get('system_logo') or '/static/icons/icon-192x192.png'

    if logo_path.startswith('/static/uploads/'):
        upload_dir = os.path.join(app.static_folder, 'uploads')
        configured_logo = os.path.join(upload_dir, os.path.basename(logo_path))
        if not os.path.isfile(configured_logo):
            try:
                logo_files = [
                    os.path.join(upload_dir, name)
                    for name in os.listdir(upload_dir)
                    if name.startswith('dept_logo_')
                    and os.path.isfile(os.path.join(upload_dir, name))
                ]
            except OSError:
                logo_files = []

            if logo_files:
                latest_logo = max(logo_files, key=os.path.getmtime)
                logo_path = f'/static/uploads/{os.path.basename(latest_logo)}'
            else:
                logo_path = '/static/icons/icon-192x192.png'
    
    # إضافة timestamp لتجنب cache المتصفح
    import time
    logo_path_with_ts = f"{logo_path}?v={int(time.time())}" if '/uploads/' in logo_path else logo_path
    
    # طباعة للتأكد
    print(f'[unified_index] Logo path from DB: {logo_path}')
    print(f'[unified_index] Logo path with timestamp: {logo_path_with_ts}')
    
    # جلب رسائل الخطأ إن وجدت
    error_msg = session.pop('login_error', None)
    active_tab = session.pop('active_tab', 'teacher')
    
    # عرض صفحة اختيار البوابة بدون تعقيد
    return render_template('unified_login.html', logo_path=logo_path_with_ts, error_msg=error_msg, active_tab=active_tab)


# ============================================
# Routes المدرس (موقع الأستاذ الأصلي)
# ============================================

@app.route('/teacher/login', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def teacher_login():
    """تسجيل دخول المدرس - يعالج POST ويرجع للصفحة الموحدة دائماً"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = verify_user(username, password)
        
        if user:
            session.clear()
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            # نحفظ الخطأ في الـ session ونرجع للصفحة الموحدة
            session['login_error'] = 'اسم المستخدم أو كلمة المرور غير صحيحة'
            session['active_tab'] = 'teacher'
            return redirect(url_for('unified_index'))
    
    return redirect(url_for('unified_index'))


@app.route('/logout')
def logout():
    """نقطة خروج عامة (generic endpoint) — تستخدمها القوالب عبر url_for('logout')"""
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('student_id', None)
    session.pop('active_tab', None)
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('unified_index'))


@app.route('/teacher/logout')
def teacher_logout():
    """تسجيل خروج المدرس"""
    session.pop('user_id', None)
    session.pop('username', None)
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('unified_index'))


# ============================================
# Routes الطالب (بوابة الطلاب)
# ============================================

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    """تسجيل دخول الطالب - يعالج POST ويرجع للصفحة الموحدة دائماً"""
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    
    if request.method == 'POST':
        # يقبل كلا الاسمين القديم والجديد
        student_code_input = (request.form.get('student_id') or request.form.get('student_code') or '').strip()
        password_input = request.form.get('password') or ''
        
        if not student_code_input:
            session['login_error'] = 'الرقم الجامعي مطلوب'
            session['active_tab'] = 'student'
            return redirect(url_for('unified_index'))
        
        # البحث بالـ student_code (الرقم الجامعي) مو بالـ id الرقمي
        student = get_student_by_code(student_code_input)
        
        if student:
            stored_password = student.get('password')
            
            if not stored_password:
                session['login_error'] = 'لم يتم تعيين كلمة مرور لحسابك بعد. يرجى التواصل مع المدرس.'
                session['active_tab'] = 'student'
                return redirect(url_for('unified_index'))
            else:
                from database import verify_student_password
                if verify_student_password(student['id'], password_input):
                    session.clear()
                    session.permanent = True
                    session['student_id'] = student['id']
                    session['student_name'] = student['full_name']
                    session['student_grade'] = student['teacher_name']
                    session['student_study_type'] = student['group_name']
                    return redirect(url_for('student_dashboard'))
                else:
                    session['login_error'] = 'كلمة المرور غير صحيحة'
                    session['active_tab'] = 'student'
                    return redirect(url_for('unified_index'))
        else:
            session['login_error'] = 'الرقم الجامعي غير صحيح، تأكد وحاول مجدداً'
            session['active_tab'] = 'student'
            return redirect(url_for('unified_index'))
    
    return redirect(url_for('unified_index'))


@app.route('/student/logout')
def student_logout():
    """تسجيل خروج الطالب"""
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('student_grade', None)
    session.pop('student_study_type', None)
    return redirect(url_for('unified_index'))


@app.route('/student/dashboard')
def student_dashboard():
    """لوحة تحكم الطالب"""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    student = get_student_by_id(student_id)
    
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    
    # جلب سجل الحضور
    attendance = get_attendance_by_student(student_id)
    
    # جلب جميع المواد
    all_subjects = get_all_subjects()
    
    # حساب إحصائيات الحضور لكل مادة
    subject_attendance = {}
    for record in attendance:
        subject_id = record['subject_id']
        if subject_id not in subject_attendance:
            subject_attendance[subject_id] = {
                'name': record.get('subject_name', f'مادة #{subject_id}'),
                'teacher': record.get('subject_teacher', ''),
                'grade': record.get('grade', ''),
                'days': 0
            }
        subject_attendance[subject_id]['days'] += 1
    
    # إحصائيات عامة
    total_days = len(set(f"{r['attendance_date']}-{r['subject_id']}" for r in attendance))
    
    stats = {
        'total_days': total_days,
        'subject_attendance': list(subject_attendance.values())
    }
    
    return render_template('student_dashboard.html',
                         student=student,
                         attendance=attendance,
                         stats=stats,
                         subjects=all_subjects,
                         subject_attendance=subject_attendance)


@app.route('/student/qr-image')
def student_qr_image():
    """توليد صورة QR للطالب"""
    if 'student_id' not in session:
        return '', 403
    
    student = get_student_by_id(session['student_id'])
    if not student:
        return '', 404
    
    qr_text = student.get('qr_code') or student.get('student_code')
    qr_img = generate_qr_code(qr_text)
    
    buffer = io.BytesIO()
    qr_img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return send_file(buffer, mimetype='image/png')


@app.route('/student/scan')
def student_scan_page():
    """صفحة ماسح QR للطالب - يمسح QR المادة ليسجل حضوره"""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    student = get_student_by_id(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))

    return render_template('student_scan.html', student=student)


@app.route('/student/api/scan-attendance', methods=['POST'])
def student_api_scan_attendance():
    """API: الطالب يمسح QR المادة ليسجل حضوره بنفسه"""
    if 'student_id' not in session:
        return jsonify({'success': False, 'message': 'يرجى تسجيل الدخول أولاً'}), 401

    data = request.get_json(force=True, silent=True)
    if not data or 'qr_data' not in data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400

    try:
        event_id, scanned_at = parse_attendance_scan_time(data)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    if event_id and attendance_sync_event_exists(event_id):
        return jsonify({'success': True, 'already_synced': True, 'message': 'تمت مزامنة الحضور مسبقاً'})

    qr_data = str(data.get('qr_data', '')).strip()

    # يجب أن يكون QR خاص بمادة
    if not qr_data.startswith('SUBJECT:'):
        return jsonify({'success': False, 'message': 'هذا QR ليس خاصاً بمادة'}), 400

    subject_qr = parse_subject_qr(qr_data)
    if not subject_qr:
        return jsonify({'success': False, 'message': 'QR المادة غير صالح أو لا يحتوي على جلسة'}), 400
    subject_id, session_token = subject_qr

    if data.get('offline_sync'):
        if not verify_subject_qr_session_at(subject_id, session_token, scanned_at):
            return jsonify({
                'success': False,
                'message': 'كان QR منتهي الصلاحية وقت المسح أو تعذر التحقق منه',
                'expired': True
            }), 403
    else:
        from database import verify_subject_qr_session
        if not verify_subject_qr_session(subject_id, session_token):
            return jsonify({
                'success': False,
                'message': 'هذا QR غير صالح أو انتهت صلاحيته. اطلب من الأستاذ توليد QR جديد.',
                'expired': True
            }), 403

    student_id = session['student_id']

    # التحقق من فترة المنع
    can_record, remaining_seconds = check_attendance_cooldown(student_id)
    if not can_record:
        remaining_time = format_remaining_time(remaining_seconds)
        return jsonify({
            'success': False,
            'message': f'انتظر {remaining_time} قبل التسجيل مجدداً',
            'cooldown_active': True,
            'remaining_seconds': remaining_seconds
        }), 429

    # التحقق من وجود المادة
    subjects = get_all_subjects()
    subject = next((s for s in subjects if s.get('id') == subject_id), None)
    if not subject:
        return jsonify({'success': False, 'message': 'المادة غير موجودة'}), 404

    student = get_student_by_id(student_id)
    group_name = student.get('group_name', 'غير معروف') if student else 'غير معروف'

    # تسجيل الحضور
    success = record_attendance(
        student_id, subject_id, group_name, recorded_at=scanned_at, event_id=event_id
    )

    if success:
        try:
            _notify_attendance_update(subject_id, {
                'type': 'new_attendance',
                'subject_id': subject_id,
                'student_name': student.get('full_name', '') if student else '',
                'student_code': student.get('student_code', '') if student else '',
                'timestamp': datetime.now().isoformat()
            })
        except Exception:
            pass  # SSE غير حرجة
        return jsonify({
            'success': True,
            'message': 'تم تسجيل حضورك بنجاح',
            'subject_name': subject.get('name', ''),
            'subject_teacher': subject.get('teacher_name', '')
        })
    else:
        return jsonify({
            'success': False,
            'message': 'أنت مسجل حضور مسبقاً لهذه المادة اليوم',
            'already_registered': True
        }), 400


@app.route('/student/api/grades', methods=['POST'])
def student_api_grades():
    """API للتحقق من كود الوصول وعرض الدرجات"""
    if 'student_id' not in session:
        return jsonify({'success': False, 'message': 'غير مصرح'}), 401
    
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'code' not in data:
        return jsonify({'success': False, 'message': 'الكود مطلوب'}), 400
    
    student_id = session['student_id']
    code = str(data.get('code') or '').strip()
    from database import get_student_grades, verify_access_code
    if verify_access_code(student_id, code):
        grades = get_student_grades(student_id)
        return jsonify({
            'success': True,
            'grades': grades,
            'message': 'تم التحقق بنجاح'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'كود غير صحيح'
        }), 400


@app.route('/student/settings')
def student_settings():
    """صفحة إعدادات الطالب"""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    
    student = get_student_by_id(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    
    return render_template('student_settings.html', student=student)


@app.route('/student/update-profile', methods=['POST'])
def student_update_profile():
    """تحديث صورة الملف الشخصي للطالب"""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    
    if 'profile_image' in request.files:
        file = request.files['profile_image']
        if file and file.filename:
            upload_dir = os.path.join(app.root_path, 'static', 'uploads', 'profiles')
            student = get_student_by_id(student_id)
            if not student:
                session.clear()
                return redirect(url_for('student_login'))
            try:
                filename = save_uploaded_image(file, upload_dir, f'student_{student_id}')
                new_image_path = f'/static/uploads/profiles/{filename}'
                from database import update_student_profile_image
                if not update_student_profile_image(student_id, new_image_path):
                    os.remove(os.path.join(upload_dir, filename))
                    raise RuntimeError('تعذر تحديث صورة الملف الشخصي في قاعدة البيانات')

                old_image = student.get('profile_image') or ''
                old_filename = os.path.basename(old_image)
                if (
                    old_image.startswith('/static/uploads/profiles/')
                    and old_filename.startswith(f'student_{student_id}_')
                ):
                    old_path = os.path.join(upload_dir, old_filename)
                    if os.path.isfile(old_path) and old_path != os.path.join(upload_dir, filename):
                        os.remove(old_path)
                flash('تم تحديث صورة الملف الشخصي بنجاح!', 'success')
            except ValueError as error:
                flash(str(error), 'error')
            except OSError as error:
                app.logger.exception('Student profile image upload failed')
                flash('تعذر حفظ الصورة. حاول مرة أخرى.', 'error')
            except RuntimeError as error:
                app.logger.exception('Student profile image database update failed')
                flash(str(error), 'error')
        else:
            flash('لم يتم اختيار صورة', 'error')
    else:
        flash('لم يتم اختيار صورة', 'error')
    
    return redirect(url_for('student_settings'))


@app.route('/student/change-password', methods=['POST'])
def student_change_password():
    """تغيير كلمة مرور الطالب"""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # التحقق من تطابق كلمة المرور الجديدة
    if new_password != confirm_password:
        flash('كلمة المرور الجديدة غير متطابقة', 'error')
        return redirect(url_for('student_settings'))
    
    # التحقق من طول كلمة المرور
    if len(new_password) < 6:
        flash('يجب أن تكون كلمة المرور 6 أحرف على الأقل', 'error')
        return redirect(url_for('student_settings'))
    
    # تحديث كلمة المرور مباشرة بدون التحقق من القديمة
    from database import set_student_password
    success = set_student_password(student_id, new_password)
    
    if success:
        flash('تم تغيير كلمة المرور بنجاح!', 'success')
    else:
        flash('حدث خطأ أثناء تغيير كلمة المرور', 'error')
    
    return redirect(url_for('student_settings'))


@app.route('/change-password', methods=['POST'])
def change_password():
    """تغيير كلمة المرور"""
    username = request.form.get('username')
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if new_password != confirm_password:
        flash('كلمة المرور الجديدة غير متطابقة', 'error')
        return redirect(url_for('teacher_login'))
    
    if len(new_password) < 6:
        flash('يجب أن تكون كلمة المرور 6 أحرف على الأقل', 'error')
        return redirect(url_for('teacher_login'))
    
    if change_user_password(username, current_password, new_password):
        flash('تم تغيير كلمة المرور بنجاح!', 'success')
    else:
        flash('اسم المستخدم أو كلمة المرور الحالية غير صحيحة', 'error')
    
    return redirect(url_for('teacher_login'))


# ============================================
# Routes المحمية (تتطلب تسجيل دخول)
# ============================================

@app.route('/index')
@login_required
def index():
    """الصفحة الرئيسية"""
    return render_template('index.html')


@app.route('/face-attendance')
@login_required
def face_attendance_page():
    """صفحة الحضور بالوجه"""
    return render_template('face_attendance.html')


@app.route('/face-attendance-offline')
@login_required
def face_attendance_offline_page():
    """صفحة الحضور بالوجه — تعمل بدون إنترنت (face-api.js)"""
    return render_template('face_attendance_offline.html')


@app.route('/face-management')
@login_required
def face_management_page():
    """صفحة إدارة Face Recognition للطلاب"""
    return render_template('face_management.html')


@app.route('/face-dashboard')
@login_required
def face_dashboard_page():
    """لوحة معلومات Face Recognition"""
    return render_template('face_dashboard.html')


@app.route('/api/face/diagnostic')
@login_required
def api_face_diagnostic():
    """API تشخيص: معلومات عن حالة Face Recognition"""
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()

        # فحص عمود face_image_data
        has_image_data_col = False
        try:
            if database.IS_POSTGRES:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='students' AND column_name='face_image_data'")
                has_image_data_col = cursor.fetchone() is not None
            else:
                cursor.execute('PRAGMA table_info(students)')
                cols = {r['name'] for r in cursor.fetchall()}
                has_image_data_col = 'face_image_data' in cols
        except Exception as e:
            pass

        # عدد الطلاب المسجلين
        if database.IS_POSTGRES:
            cursor.execute("SELECT COUNT(*) as count FROM students WHERE face_enrolled = TRUE")
        else:
            cursor.execute("SELECT COUNT(*) as count FROM students WHERE face_enrolled = 1")
        enrolled_count = cursor.fetchone()['count']

        # عينة من الطلاب المسجلين
        if has_image_data_col:
            if database.IS_POSTGRES:
                cursor.execute("""
                    SELECT id, full_name, face_image_path, 
                           CASE WHEN face_image_data IS NOT NULL THEN length(face_image_data) ELSE 0 END as data_length
                    FROM students 
                    WHERE face_enrolled = TRUE 
                    LIMIT 5
                """)
            else:
                cursor.execute("""
                    SELECT id, full_name, face_image_path,
                           CASE WHEN face_image_data IS NOT NULL THEN length(face_image_data) ELSE 0 END as data_length
                    FROM students 
                    WHERE face_enrolled = 1 
                    LIMIT 5
                """)
        else:
            if database.IS_POSTGRES:
                cursor.execute("""
                    SELECT id, full_name, face_image_path, 0 as data_length
                    FROM students 
                    WHERE face_enrolled = TRUE 
                    LIMIT 5
                """)
            else:
                cursor.execute("""
                    SELECT id, full_name, face_image_path, 0 as data_length
                    FROM students 
                    WHERE face_enrolled = 1 
                    LIMIT 5
                """)
        samples = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'database_type': 'PostgreSQL' if database.IS_POSTGRES else 'SQLite',
            'has_face_image_data_column': has_image_data_col,
            'enrolled_students_count': enrolled_count,
            'sample_students': samples
        })
    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/generate')
@login_required
def generate_page():
    """صفحة توليد QR"""
    return render_template('generate.html')


@app.route('/api/generate-qr', methods=['POST'])
@login_required
def generate_qr():
    """توليد QR Code وحفظه في قاعدة البيانات، مع دعم نوعين: طالب أو مادة."""
    try:
        data = request.get_json(force=True, silent=True)

        if not data:
            return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400

        full_name = (data.get('full_name') or '').strip()
        department = (data.get('department') or '').strip()
        teacher_name = (data.get('teacher_name') or '').strip()
        group_name = (data.get('group_name') or '').strip()
        subject_id = data.get('subject_id')
        qr_mode = data.get('qr_mode', 'student')

        if subject_id:
            try:
                subject_id = int(subject_id)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'معرف المادة غير صحيح'}), 400

            subject = next((s for s in get_all_subjects() if s.get('id') == subject_id), None)
            if subject:
                department = department or subject.get('department', '')
                teacher_name = teacher_name or subject.get('teacher_name', '')
                group_name = group_name or subject.get('course_type', '')

        if qr_mode == 'subject':
            # استخرج subject_id من البيانات المرسلة
            if not subject_id:
                return jsonify({'success': False, 'message': 'يرجى اختيار المادة أولاً لتوليد QR'}), 400

            subjects_list = get_all_subjects()
            subject = next((s for s in subjects_list if s.get('id') == subject_id), None)
            if not subject:
                return jsonify({'success': False, 'message': 'المادة غير موجودة في قاعدة البيانات'}), 404

            # ✅ أنشئ جلسة QR جديدة فريدة (تلغي القديمة تلقائياً) - صالحة 30 دقيقة
            from database import create_subject_qr_session
            session_data = create_subject_qr_session(subject_id, duration_minutes=30)
            
            if not session_data:
                return jsonify({'success': False, 'message': 'فشل إنشاء جلسة QR'}), 500

            session_token = session_data['token']
            expires_at = session_data['expires_at']

            dept  = subject.get('department', '')
            tname = subject.get('teacher_name', '')
            gname = subject.get('course_type', '')
            sname = subject.get('name', '')

            # ✅ QR يحتوي على subject_id + session_token
            qr_content = f"SUBJECT:{subject_id}|SESSION:{session_token}|DEPT:{dept}|TEACHER:{tname}|GROUP:{gname}|NAME:{sname}"
            qr_img = generate_qr_code(qr_content)
            buffered = io.BytesIO()
            qr_img.save(buffered, format='PNG')
            qr_base64 = base64.b64encode(buffered.getvalue()).decode()

            return jsonify({
                'success': True,
                'qr_code': f"data:image/png;base64,{qr_base64}",
                'subject_id': subject_id,
                'subject': subject,
                'session_token': session_token,
                'expires_at': expires_at,
                'duration_minutes': 30,
                'message': 'تم توليد QR جديد - صالح لمدة 30 دقيقة',
                'mode': 'subject'
            })

        if not full_name:
            full_name = f"طالب {datetime.now().strftime('%d%m%y%H%M%S')}"

        if not all([department, teacher_name, group_name]):
            return jsonify({'success': False, 'message': 'يرجى اختيار المرحلة والمادة والكورس بشكل صحيح'}), 400

        import uuid
        requested_student_code = (data.get('student_code') or '').strip().upper()
        if requested_student_code and (
            not requested_student_code.isascii()
            or not requested_student_code.isalnum()
            or not 8 <= len(requested_student_code) <= 32
        ):
            return jsonify({'success': False, 'message': 'رمز الطالب غير صالح'}), 400

        student_code = requested_student_code or str(uuid.uuid4())[:8].upper()

        if requested_student_code:
            existing_student = get_student_by_code(student_code)
            if existing_student:
                same_student = all(existing_student.get(key) == value for key, value in (
                    ('full_name', full_name),
                    ('department', department),
                    ('teacher_name', teacher_name),
                    ('group_name', group_name)
                ))
                if not same_student:
                    return jsonify({'success': False, 'message': 'رمز الطالب مستخدم مسبقاً'}), 409

                existing_image = generate_qr_code(existing_student.get('qr_code') or '')
                existing_buffer = io.BytesIO()
                existing_image.save(existing_buffer, format='PNG')
                existing_base64 = base64.b64encode(existing_buffer.getvalue()).decode()
                return jsonify({
                    'success': True,
                    'qr_code': f"data:image/png;base64,{existing_base64}",
                    'student_code': student_code,
                    'student': existing_student,
                    'message': 'تمت استعادة الطالب المحفوظ مسبقاً',
                    'mode': 'student'
                })

        qr_content = f"CODE:{student_code}|NAME:{full_name}|DEPT:{department}|TEACHER:{teacher_name}|GROUP:{group_name}"
        if subject_id:
            qr_content += f"|SUBJECT:{subject_id}"

        qr_img = generate_qr_code(qr_content)

        buffered = io.BytesIO()
        qr_img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        student_id = add_student(full_name, department, teacher_name, group_name, student_code, qr_content, qr_base64)

        if not student_id:
            return jsonify({'success': False, 'message': 'فشل إضافة الطالب'}), 400

        student = get_student_by_id(student_id)

        if not student:
            return jsonify({'success': False, 'message': 'خطأ: لم يتم حفظ الطالب'}), 400

        print(f'[API] Student added: {full_name} ({student_code})')

        return jsonify({
            'success': True,
            'qr_code': f"data:image/png;base64,{qr_base64}",
            'student_code': student_code,
            'student': student,
            'message': 'تم التوليد والحفظ بنجاح',
            'mode': 'student'
        })

    except Exception as e:
        import traceback
        print(f"[API Error] generate_qr: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/scanner')
@login_required
def scanner_page():
    """صفحة ماسح QR"""
    subjects = get_all_subjects()
    return render_template('scanner.html', subjects=subjects)


@app.route('/api/scan-qr', methods=['POST'])
@login_required
def api_scan_qr():
    """API لمسح QR code وتسجيل الحضور، يدعم QR الطالب وQR المادة."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception as e:
        print(f'[API] JSON Parse Error: {e}')
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400

    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400

    try:
        event_id, scanned_at = parse_attendance_scan_time(data)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    qr_data = str(data.get('qr_data') or '').strip()
    subject_id = data.get('subject_id')
    mode = (data.get('mode') or 'student').strip().lower()

    # Subject QR tokens must be valid for both live and queued scans.
    if qr_data.startswith('SUBJECT:'):
        subject_qr = parse_subject_qr(qr_data)
        if not subject_qr:
            return jsonify({'success': False, 'message': 'QR المادة غير صالح أو لا يحتوي على جلسة'}), 400
        qr_subject_id, session_token = subject_qr
        if subject_id is not None:
            try:
                if int(subject_id) != qr_subject_id:
                    return jsonify({'success': False, 'message': 'المادة المحددة لا تطابق QR'}), 400
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'معرف المادة غير صالح'}), 400
        subject_id = qr_subject_id

        if data.get('offline_sync'):
            valid_session = verify_subject_qr_session_at(subject_id, session_token, scanned_at)
        else:
            from database import verify_subject_qr_session
            valid_session = verify_subject_qr_session(subject_id, session_token)
        if not valid_session:
            return jsonify({
                'success': False,
                'message': 'QR المادة غير صالح أو منتهي الصلاحية',
                'expired': True
            }), 403

    if not qr_data:
        return jsonify({'success': False, 'message': 'بيانات غير كاملة'}), 400

    if event_id and attendance_sync_event_exists(event_id):
        return jsonify({'success': True, 'already_synced': True, 'message': 'تمت مزامنة الحضور مسبقاً'})

    # subject_id مطلوب فقط لـ QR الطالب
    if not qr_data.startswith('SUBJECT:') and not subject_id:
        return jsonify({'success': False, 'message': 'اختر المادة أولاً'}), 400

    if subject_id:
        try:
            subject_id = int(subject_id)
        except (ValueError, TypeError) as e:
            print(f'[API] Subject ID conversion error: {e}')
            return jsonify({'success': False, 'message': 'subject_id غير صالح'}), 400

    try:
        print(f'[API] Processing QR: {qr_data}, Subject: {subject_id}, Mode: {mode}')

        if qr_data.startswith('SUBJECT:'):
            subject_result = record_attendance_for_subject(
                subject_id, group_name='مادة', recorded_at=scanned_at, event_id=event_id
            )
            if not subject_result.get('success'):
                return jsonify({'success': False, 'message': subject_result.get('message', 'فشل تسجيل حضور المادة')}), 400
            return jsonify({
                'success': True,
                'message': subject_result.get('message', 'تم تسجيل حضور المادة بنجاح'),
                'mode': 'subject',
                'saved': subject_result.get('saved', 0),
                'total': subject_result.get('total', 0)
            })

        if qr_data.startswith('CODE:'):
            code_start = qr_data.find('CODE:') + 5
            code_end = qr_data.find('|', code_start)
            if code_end == -1:
                code_end = len(qr_data)
            student_code = qr_data[code_start:code_end].strip()
        else:
            student_code = qr_data.strip()

        print(f'[API] Extracted student code: {student_code}')
        student = get_student_by_code(student_code)

        if not student:
            return jsonify({'success': False, 'message': f'الطالب غير موجود (Code: {student_code})'}), 404

        student_id = student.get('id')
        if not student_id:
            return jsonify({'success': False, 'message': 'خطأ: بيانات الطالب غير صحيحة'}), 400

        can_record, remaining_seconds = check_attendance_cooldown(student_id)
        if not can_record:
            remaining_time = format_remaining_time(remaining_seconds)
            return jsonify({
                'success': False,
                'message': f'⏳ فترة المنع! يرجى الانتظار {remaining_time} قبل إعادة التسجيل',
                'cooldown_active': True,
                'remaining_seconds': remaining_seconds,
                'remaining_time_formatted': remaining_time
            }), 429

        group_name = student.get('group_name', 'غير معروف')
        success = record_attendance(
            student_id, subject_id, group_name, recorded_at=scanned_at, event_id=event_id
        )

        if success:
            subjects = get_all_subjects() or []
            subject = next((s for s in subjects if s.get('id') == subject_id), None)
            try:
                _notify_attendance_update(subject_id, {
                    'type': 'new_attendance',
                    'subject_id': subject_id,
                    'student_name': student.get('full_name', ''),
                    'student_code': student.get('student_code', ''),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception:
                pass  # SSE غير حرجة
            return jsonify({
                'success': True,
                'message': f"✅ تم تسجيل حضور {student.get('full_name', 'الطالب')} بنجاح",
                'student': student,
                'subject': subject,
                'group_name': group_name,
                'mode': 'student'
            })

        return jsonify({
            'success': False,
            'message': 'الطالب مسجل حضور مسبقاً لهذا اليوم في هذه المادة',
            'already_registered': True,
            'student': student,
            'mode': 'student'
        }), 400

    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f'[ERROR] {error_msg}')
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'خطأ في السيرفر: {error_msg}'}), 500


@app.route('/students')
@login_required
def students_page():
    """صفحة قائمة الطلاب — هيكل الصفحة فقط، البيانات تأتي عبر API"""
    return render_template('students.html', students=[])


@app.route('/api/students-list')
@login_required
def api_students_list():
    """API: جلب قائمة الطلاب بشكل سريع"""
    try:
        students = get_all_students()
        result = []
        for s in students:
            result.append({
                'id': s['id'],
                'full_name': s.get('full_name', ''),
                'student_code': s.get('student_code', ''),
                'department': s.get('department', ''),
                'teacher_name': s.get('teacher_name', ''),
                'group_name': s.get('group_name', ''),
                'profile_image': s.get('profile_image') or '',
                'password': bool(s.get('password')),
                'face_enrolled': bool(s.get('face_enrolled')),
                'face_image_path': bool(s.get('face_image_path')),
            })
        return jsonify({'success': True, 'students': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/student/<int:student_id>')
@login_required
def student_detail(student_id):
    """صفحة تفاصيل الطالب - ✅ استخدام الصورة المخزنة"""
    student = get_student_by_id(student_id)
    if not student:
        flash('الطالب غير موجود', 'error')
        return redirect(url_for('students_page'))
    
    attendance = get_attendance_by_student(student_id)
    
    # ✅ استخدام الصورة المخزنة في قاعدة البيانات
    qr_base64 = student.get('qr_image')
    
    # ✅ للطلاب القدامى الذين ليس لديهم صورة مخزنة، نولدها مؤقتاً
    if not qr_base64:
        qr_img = generate_qr_code(student['qr_code'])
        qr_base64 = qr_to_base64(qr_img).replace('data:image/png;base64,', '')
    
    return render_template('student_detail.html', 
                         student=student, 
                         attendance=attendance,
                         qr_code=f"data:image/png;base64,{qr_base64}")

@app.route('/subjects')
@login_required
def subjects_page():
    """صفحة المواد"""
    subjects = get_all_subjects()
    return render_template('subjects.html', subjects=subjects)

@app.route('/api/add-subject', methods=['POST'])
@login_required
def api_add_subject():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'success': False, 'message': 'لم يتم استلام أي بيانات'}), 400
        
        name = (data.get('name') or '').strip()
        department = (data.get('department') or '').strip() or 'عام'
        teacher_name = (data.get('teacher_name') or '').strip()
        grade = (data.get('grade') or 'الأولى').strip()
        course_type = (data.get('course_type') or 'أول').strip()
        
        if not all([name, teacher_name, grade, course_type]):
            return jsonify({'success': False, 'message': 'يرجى ملء اسم المادة والأستاذ والمرحلة والكورس'}), 400
        
        import uuid
        import time
        code = str(uuid.uuid4())[:6].upper() + str(int(time.time()))[-4:]
        
        subject_id = add_subject(name, code, department, teacher_name, grade, course_type)
        
        if subject_id:
            return jsonify({'success': True, 'subject_id': subject_id})
        else:
            return jsonify({'success': False, 'message': 'حدث خطأ في إضافة المادة'}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطأ في الخادم: {str(e)}'}), 500


@app.route('/attendance')
@login_required
def attendance_page():
    """صفحة سجل الحضور"""
    subjects = get_all_subjects()
    today = datetime.now().strftime('%Y-%m-%d')
    today_stats = get_today_attendance_stats()
    
    return render_template('attendance.html', 
                         subjects=subjects,
                         today=today,
                         today_stats=today_stats)


@app.route('/api/attendance/<int:subject_id>')
@login_required
def api_get_attendance(subject_id):
    """API للحصول على سجل الحضور"""
    date = request.args.get('date')
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    used_date = date

    # تحقق من وجود حضور فعلي في التاريخ المحدد
    count_in_date = get_attendance_count_by_subject_date(subject_id, date)
    if count_in_date == 0:
        fallback_date = get_subject_latest_attendance_date_before(subject_id, date)
        if fallback_date and fallback_date != date:
            used_date = fallback_date

    stage = request.args.get('stage')
    attendance = get_students_attendance_status(subject_id, used_date, stage)

    subjects = get_all_subjects()
    subject = next((s for s in subjects if s['id'] == subject_id), None)

    return jsonify({
        'success': True,
        'attendance': attendance,
        'subject': subject,
        'requested_date': date,
        'used_date': used_date,
        'count_in_request_date': count_in_date
    })


@app.route('/api/attendance/latest_date/<int:subject_id>')
@login_required
def api_get_latest_attendance_date(subject_id):
    """API للحصول على أحدث تاريخ حضور للمادة"""
    latest_date = get_subject_latest_attendance_date(subject_id)
    return jsonify({'success': True, 'latest_date': latest_date})


@app.route('/api/delete-student/<int:student_id>', methods=['DELETE'])
@login_required
def api_delete_student(student_id):
    """API لحذف طالب"""
    try:
        success = delete_student(student_id)
        if success:
            return jsonify({'success': True, 'message': 'تم حذف الطالب بنجاح'})
        else:
            return jsonify({'success': False, 'message': 'فشل حذف الطالب'}), 400
    except Exception as e:
        print(f'[API Error] delete_student: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/reset-student-password/<int:student_id>', methods=['POST'])
@login_required
def api_reset_student_password(student_id):
    """API لتعيين كلمة مرور جديدة للطالب من قبل المدرس"""
    try:
        student = get_student_by_id(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'الطالب غير موجود'}), 404
        
        data = request.get_json(force=True, silent=True) or {}
        new_password = data.get('new_password', '').strip()
        
        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'message': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'}), 400
        
        from database import set_student_password
        success = set_student_password(student_id, new_password)
        
        if success:
            print(f'[Admin] ✓ Password set for student: {student.get("full_name")} (ID: {student_id})')
            return jsonify({'success': True, 'message': 'تم تعيين كلمة المرور بنجاح'})
        else:
            return jsonify({'success': False, 'message': 'فشل تعيين كلمة المرور'}), 400
    except Exception as e:
        print(f'[API Error] reset_student_password: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/promote-students', methods=['POST'])
@login_required
def api_promote_students():
    """API لترقية المرحلة الدراسية لمجموعة طلاب"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        from_grade = data.get('from_grade', '').strip()
        to_grade = data.get('to_grade', '').strip()

        if not from_grade or not to_grade:
            return jsonify({'success': False, 'message': 'يرجى تحديد المرحلتين'}), 400
        if from_grade == to_grade:
            return jsonify({'success': False, 'message': 'المرحلتان متماثلتان'}), 400

        from database import promote_students_grade
        count = promote_students_grade(from_grade, to_grade)

        print(f'[Admin] ✓ Promoted {count} students from {from_grade} to {to_grade}')
        return jsonify({'success': True, 'count': count,
                        'message': f'تم ترقية {count} طالب من {from_grade} إلى {to_grade}'})
    except Exception as e:
        print(f'[API Error] promote_students: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/undo-promotion', methods=['POST'])
@login_required
def api_undo_promotion():
    """API للتراجع عن آخر عملية ترقية"""
    try:
        from database import undo_last_promotion
        count, message = undo_last_promotion()
        if count > 0:
            return jsonify({'success': True, 'count': count, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        print(f'[API Error] undo_promotion: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/check-promotion-log')
@login_required
def api_check_promotion_log():
    """التحقق من وجود سجل ترقية"""
    try:
        from database import get_last_promotion_log
        log = get_last_promotion_log()
        if log:
            return jsonify({'has_log': True, 'from_grade': log['from_grade'], 'to_grade': log['to_grade']})
        return jsonify({'has_log': False})
    except Exception as e:
        return jsonify({'has_log': False})


@app.route('/api/delete-subject/<int:subject_id>', methods=['DELETE'])
@login_required
def api_delete_subject(subject_id):
    """API لحذف مادة"""
    try:
        success = delete_subject(subject_id)
        if success:
            return jsonify({'success': True, 'message': 'تم حذف المادة بنجاح'})
        else:
            return jsonify({'success': False, 'message': 'فشل حذف المادة'}), 400
    except Exception as e:
        print(f'[API Error] delete_subject: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/get-subjects')
@login_required
def api_get_subjects():
    """API للحصول على المواد"""
    try:
        department = request.args.get('department')
        
        if department:
            subjects = get_subjects_by_department(department)
        else:
            subjects = get_all_subjects()
        
        if subjects is None:
            subjects = []
        
        return jsonify({'success': True, 'subjects': subjects})
    except Exception as e:
        print(f'[API Error] api_get_subjects: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}', 'subjects': []}), 500

@app.route('/api/get-students')
@login_required
def api_get_students():
    """API للحصول على جميع الطلاب"""
    try:
        students = get_all_students()
        if students is None:
            students = []
        return jsonify({'success': True, 'students': students})
    except Exception as e:
        print(f'[API Error] api_get_students: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}', 'students': []}), 500

# ============================================
# إعدادات النظام
# ============================================
 
import os
from werkzeug.utils import secure_filename

@app.route('/settings')
@login_required
def settings_page():
    """صفحة الإعدادات"""
    from database import get_settings, get_all_users
    import time
    settings = get_settings()
    
    # أضف timestamp لمنع cache الصور
    if settings.get('dept_image') and '/uploads/' in settings.get('dept_image', ''):
        settings['dept_image_url'] = settings['dept_image'] + '?v=' + str(int(time.time()))
    else:
        settings['dept_image_url'] = settings.get('dept_image', '')
    
    if session.get('username') == 'admin':
        users = get_all_users()
    else:
        users = []
    
    return render_template('settings.html', settings=settings, users=users, is_admin=(session.get('username') == 'admin'))


@app.route('/update-settings', methods=['POST'])
@login_required
@admin_required  # بس الـ admin يقدر يحدث الإعدادات العامة
def update_settings():
    """تحديث إعدادات النظام"""
    from database import get_settings, save_settings
    
    setting_type = request.form.get('setting_type')
    settings = get_settings()
    old_logo_path = settings.get('dept_image')
    new_logo_path = None
    
    if setting_type == 'general':
        settings['dept_name'] = request.form.get('dept_name', 'قسم علوم الحاسوب')
        settings['dept_subtitle'] = request.form.get('dept_subtitle', 'نظام إدارة الحضور والغياب')
        
        # معالجة صورة القسم (وتستخدم أيضاً كشعار في صفحة تسجيل الدخول)
        if 'dept_image' in request.files:
            file = request.files['dept_image']
            if file and file.filename:
                upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                try:
                    filename = save_uploaded_image(file, upload_dir, 'dept_logo')
                except ValueError as error:
                    flash(str(error), 'error')
                    return redirect(url_for('settings_page'))
                new_logo_path = f'/static/uploads/{filename}'
                settings['dept_image'] = new_logo_path
                settings['system_logo'] = new_logo_path
    
    save_settings(settings)
    if new_logo_path and old_logo_path and old_logo_path != new_logo_path:
        old_filename = os.path.basename(old_logo_path)
        if old_filename.startswith('dept_logo_'):
            old_path = os.path.join(app.root_path, 'static', 'uploads', old_filename)
            if os.path.isfile(old_path):
                os.remove(old_path)
    flash('تم حفظ الإعدادات بنجاح! ✓', 'success')
    return redirect(url_for('settings_page'))


@app.route('/add-user', methods=['POST'])
@login_required
@admin_required  # بس الـ admin يقدر يضيف مستخدمين
def add_user():
    """إضافة مستخدم جديد"""
    from database import add_new_user
    
    username = request.form.get('username')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    
    if password != confirm_password:
        flash('كلمات المرور غير متطابقة!', 'error')
        return redirect(url_for('settings_page'))
    
    if len(password) < 6:
        flash('يجب أن تكون كلمة المرور 6 أحرف على الأقل!', 'error')
        return redirect(url_for('settings_page'))
    
    if add_new_user(username, password):
        flash(f'تم إضافة المستخدم {username} بنجاح!', 'success')
    else:
        flash('اسم المستخدم موجود مسبقاً!', 'error')
    
    return redirect(url_for('settings_page'))


@app.route('/delete-user/<username>', methods=['DELETE'])
@login_required
@admin_required  # بس الـ admin يقدر يحذف مستخدمين
def delete_user_route(username):
    """حذف مستخدم"""
    try:
        if username == session.get('username'):
            return jsonify({'success': False, 'message': 'لا يمكنك حذف حسابك الحالي!'})
        
        if username == 'admin':
            return jsonify({'success': False, 'message': 'لا يمكن حذف المستخدم الرئيسي!'})
        
        success = delete_user_by_username(username)
        if success:
            return jsonify({'success': True, 'message': 'تم حذف المستخدم بنجاح'})
        else:
            return jsonify({'success': False, 'message': 'فشل حذف المستخدم'}), 400
    except Exception as e:
        print(f'[API Error] delete_user: {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/change-password-admin', methods=['POST'])
@login_required
def change_password_admin():
    """تغيير كلمة المرور - أي مستخدم يقدر يغير كلمة مروره"""
    from database import change_user_password
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # التحقق من تطابق كلمات المرور
    if new_password != confirm_password:
        flash('كلمات المرور الجديدة غير متطابقة!', 'error')
        return redirect(url_for('settings_page'))
    
    if len(new_password) < 6:
        flash('يجب أن تكون كلمة المرور 6 أحرف على الأقل!', 'error')
        return redirect(url_for('settings_page'))
    
    # المستخدم يغير بس كلمة مروره، الـ admin يقدر يغير لأي شخص (اختياري)
    username = session.get('username')
    
    if change_user_password(username, current_password, new_password):
        flash('تم تغيير كلمة المرور بنجاح!', 'success')
    else:
        flash('كلمة المرور الحالية غير صحيحة!', 'error')
    
    return redirect(url_for('settings_page'))


# ===== صفحة الدرجات =====

@app.route('/grades')
@login_required
def grades_page():
    from database import get_all_students, get_all_subjects, get_all_active_codes
    students = get_all_students()
    subjects = get_all_subjects()
    codes = get_all_active_codes()
    return render_template('student_grades.html', students=students, subjects=subjects, codes=codes)


@app.route('/api/student/<int:student_id>/generate-code', methods=['POST'])
@login_required
def api_generate_code(student_id):
    from database import generate_access_code, get_student_by_id
    code = generate_access_code(student_id)
    if code:
        student = get_student_by_id(student_id)
        return jsonify({
            'success': True,
            'code': code,
            'student_id': student_id,
            'student_name': student['full_name'] if student else '',
            'student_code': student['student_code'] if student else ''
        })
    return jsonify({'success': False, 'message': 'فشل توليد الكود'})


@app.route('/api/access-code/<int:code_id>/delete', methods=['DELETE'])
@login_required
def api_delete_access_code(code_id):
    from database import delete_access_code
    if delete_access_code(code_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'فشل الحذف'})


@app.route('/api/student/<int:student_id>/add-grade', methods=['POST'])
@login_required
def api_add_grade(student_id):
    from database import add_grade
    data = request.get_json()
    ok = add_grade(
        student_id,
        data.get('subject_id'),
        data.get('grade'),
        data.get('max_grade', 100),
        data.get('exam_type', 'نهائي'),
        data.get('notes', '')
    )
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'فشل إضافة الدرجة'})


@app.route('/api/student/<int:student_id>/grades')
@login_required
def api_get_student_grades(student_id):
    from database import get_student_grades
    grades = get_student_grades(student_id)
    return jsonify({'success': True, 'grades': grades})


@app.route('/api/grade/<int:grade_id>/delete', methods=['DELETE'])
@login_required
def api_delete_grade(grade_id):
    from database import delete_grade
    if delete_grade(grade_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'فشل الحذف'})


# ============================================
# صفحة الشبكة وتشغيل Hotspot
# ============================================

@app.route('/network')
@login_required
def network_page():
    return render_template('network.html')


def get_public_base_url():
    """يرجع الرابط العام للموقع إذا كان مستضافاً على Railway/Render، وإلا None"""
    domain = (os.environ.get('RAILWAY_PUBLIC_DOMAIN')
              or os.environ.get('RAILWAY_STATIC_URL')
              or os.environ.get('RENDER_EXTERNAL_HOSTNAME'))
    if domain:
        domain = domain.replace('https://', '').replace('http://', '').strip().rstrip('/')
        if domain:
            return f'https://{domain}'
    return None


@app.route('/api/network-info')
@login_required
def api_network_info():
    import socket, subprocess
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    hotspot_ip = "192.168.137.1"
    hotspot_active = False
    detection_method = "none"

    # الطريقة 1: فحص netsh hosted network (الطريقة القديمة)
    try:
        result = subprocess.run(['netsh', 'wlan', 'show', 'hostednetwork'],
                                capture_output=True, text=True, timeout=3)
        if 'Started' in result.stdout or 'تم بدء' in result.stdout:
            hotspot_active = True
            detection_method = "netsh-hostednetwork"
    except Exception:
        pass

    # الطريقة 2: فحص network adapters عبر PowerShell
    if not hotspot_active:
        try:
            ps_command = '''
            $adapters = Get-NetAdapter | Where-Object {
                ($_.InterfaceDescription -like "*Wi-Fi Direct*" -or 
                 $_.InterfaceDescription -like "*Hosted*" -or
                 $_.InterfaceDescription -like "*Microsoft Wi-Fi Direct*" -or
                 $_.Name -like "*Local Area Connection*") -and 
                $_.Status -eq "Up"
            }
            $adapters.Count
            '''
            result = subprocess.run(
                ['powershell', '-Command', ps_command],
                capture_output=True, text=True, timeout=5)
            count = int(result.stdout.strip() or '0')
            if count > 0:
                hotspot_active = True
                detection_method = "powershell-adapter"
        except Exception:
            pass

    # الطريقة 3: فحص IP address على 192.168.137.x
    if not hotspot_active:
        try:
            ps_command = '''
            $hotspotIP = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
                $_.IPAddress -like "192.168.137.*"
            }
            if ($hotspotIP) { "FOUND" } else { "NONE" }
            '''
            result = subprocess.run(
                ['powershell', '-Command', ps_command],
                capture_output=True, text=True, timeout=3)
            if 'FOUND' in result.stdout:
                hotspot_active = True
                detection_method = "ip-check"
        except Exception:
            pass

    # الطريقة 4: محاولة الاتصال بـ 192.168.137.1
    if not hotspot_active:
        try:
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            # محاولة الاتصال بالـ gateway المتوقع
            result = test_socket.connect_ex(('192.168.137.1', 445))  # SMB port
            test_socket.close()
            if result == 0:
    
                hotspot_active = True
                detection_method = "connection-test"
        except Exception:
            pass

    # تحديد IP الطالب
    student_ip = hotspot_ip if hotspot_active else local_ip
    server_port = request.environ.get('SERVER_PORT') or os.environ.get('PORT') or '5000'

    # ✅ إذا الموقع مستضاف على Railway/Render → الرابط العام هو الصحيح للطلاب
    public_url = get_public_base_url()
    if public_url:
        student_url = public_url
        teacher_url = public_url
        hosted_mode = True
    else:
        student_url = f'http://{student_ip}:{server_port}'
        teacher_url = f'http://{local_ip}:{server_port}'
        hosted_mode = False

    return jsonify({
        'success': True,
        'local_ip': local_ip,
        'hotspot_ip': hotspot_ip,
        'server_port': server_port,
        'hotspot_active': hotspot_active,
        'detection_method': detection_method,
        'student_ip': student_ip,
        'student_url': student_url,
        'teacher_url': teacher_url,
        'hosted_mode': hosted_mode
    })


@app.route('/api/start-hotspot')
@login_required
def api_start_hotspot():
    # ✅ عند الاستضافة على Railway/Render: الهوتسبوت يُشغّل من ويندوز فقط لمشاركة الإنترنت
    if get_public_base_url():
        flash('الموقع مستضاف على السحابة. شغّل الهوتسبوت من جهازك لمشاركة الإنترنت، والطلاب يفتحون رابط الموقع العام.', 'success')
        return redirect(url_for('network_page'))
    import subprocess
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hotspot.ps1')
    try:
        subprocess.Popen(
            ['powershell', '-Command',
             f'Start-Process powershell -ArgumentList \'-ExecutionPolicy Bypass -File "{script}"\' -Verb RunAs'],
            shell=True)
        flash('جاري تشغيل شبكة الحضور...', 'success')
    except Exception as e:
        flash(f'تعذر تشغيل الشبكة: {e}', 'error')
    return redirect(url_for('network_page'))


@app.route('/api/stop-hotspot')
@login_required
def api_stop_hotspot():
    if get_public_base_url():
        return redirect(url_for('network_page'))
    import subprocess
    try:
        subprocess.Popen(
            ['powershell', '-Command',
             'Start-Process powershell -ArgumentList \'-Command "netsh wlan stop hostednetwork"\' -Verb RunAs'],
            shell=True)
        flash('تم إيقاف الشبكة', 'success')
    except Exception as e:
        flash(f'تعذر الإيقاف: {e}', 'error')
    return redirect(url_for('network_page'))


# ═══════════════════════════════════════════════════════════════════════════
# FACE RECOGNITION APIs
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/face/enroll', methods=['POST'])
@login_required
def api_face_enroll():
    """API: تسجيل وجه طالب"""
    import time
    t_start = time.time()
    try:
        from face_recognition_utils import FaceRecognitionManager, save_face_image
        from database import update_student_face_encoding, get_student_by_id
        
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400
        
        student_id = data.get('student_id')
        image_data = data.get('image_data')
        
        if not student_id or not image_data:
            return jsonify({'success': False, 'message': 'معرف الطالب والصورة مطلوبان'}), 400
        
        student = get_student_by_id(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'الطالب غير موجود'}), 404
        
        t1 = time.time()
        result = FaceRecognitionManager.enroll_face(image_data, is_base64=True)
        print(f'[TIMING] enroll_face took: {time.time()-t1:.2f}s | total so far: {time.time()-t_start:.2f}s')
        
        if not result['success']:
            return jsonify(result), 400
        
        face_image_path = save_face_image(image_data, student_id)
        print(f'[Enroll] save_face_image returned: {face_image_path}')

        if not face_image_path:
            return jsonify({'success': False, 'message': 'تعذر حفظ صورة الوجه'}), 400

        # تحقق فعلي من وجود الملف
        import os as _os
        _full = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), face_image_path.lstrip('/').replace('/', _os.sep))
        print(f'[Enroll] Expected file at: {_full} | exists: {_os.path.isfile(_full)}')

        # حفظ الصورة كـ base64 في DB (تبقى على Railway بعد كل deployment)
        import base64 as _b64
        raw_b64 = image_data.split(',')[1] if ',' in image_data else image_data

        success = update_student_face_encoding(
            student_id,
            result['face_encoding'],
            face_image_path,
            face_image_data=raw_b64
        )
        
        print(f'[TIMING] total enroll: {time.time()-t_start:.2f}s')
        
        if success:
            old_face_image_path = student.get('face_image_path')
            if old_face_image_path and old_face_image_path != face_image_path:
                from face_recognition_utils import delete_face_image
                delete_face_image(old_face_image_path)
            return jsonify({
                'success': True,
                'message': f'تم تسجيل وجه {student["full_name"]} بنجاح',
                'student_name': student['full_name'],
                'face_image_url': f'/api/face/image/{student_id}'
            })
        else:
            from face_recognition_utils import delete_face_image
            delete_face_image(face_image_path)
            return jsonify({'success': False, 'message': 'فشل حفظ بيانات الوجه'}), 500
            
    except Exception as e:
        print(f'[Face Enroll Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/recognize', methods=['POST'])
@login_required
def api_face_recognize():
    """API: التعرف على وجه من الكاميرا"""
    import time
    t0 = time.time()
    try:
        from face_recognition_utils import FaceRecognitionManager
        from database import (
            get_all_enrolled_faces, 
            record_face_attendance, 
            get_student_by_id,
            get_face_attendance_session,
            log_face_recognition_attempt
        )
        
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400
        
        image_data = data.get('image_data')
        try:
            subject_id = int(data.get('subject_id'))
            session_id = int(data.get('session_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'معرف المادة أو الجلسة غير صالح'}), 400

        if not image_data:
            return jsonify({'success': False, 'message': 'الصورة مطلوبة'}), 400

        face_session = get_face_attendance_session(session_id)
        if (
            not face_session
            or face_session.get('status') != 'ACTIVE'
            or int(face_session.get('subject_id')) != subject_id
        ):
            return jsonify({'success': False, 'message': 'جلسة الحضور غير نشطة أو لا تطابق المادة'}), 409

        threshold = float(face_session.get('recognition_threshold') or 0.75)
        if threshold > 1.0 or threshold < 0.1:
            threshold = 0.75
        
        t1 = time.time()
        enrolled_faces = get_all_enrolled_faces()
        print(f'[TIMING] get_faces: {time.time()-t1:.2f}s ({len(enrolled_faces)} faces)')
        
        if not enrolled_faces:
            return jsonify({'success': False, 'message': 'لا يوجد طلاب مسجلين'}), 400
        
        t2 = time.time()

        # ── الخطوة 1: تحقق من وجود وجه داخل صورة المربع (box_image) ──────
        box_image = data.get('box_image')
        if box_image:
            from face_recognition_utils import _base64_to_bgr, _detect_face
            try:
                box_bgr = _base64_to_bgr(box_image)
                face_in_box = _detect_face(box_bgr)
                print(f'[BOX_CHECK] face_in_box={face_in_box}')
                if face_in_box is None:
                    if session_id:
                        log_face_recognition_attempt(None, session_id, 'NO_FACE', 0.0, 'لا وجه داخل المربع')
                    return jsonify({
                        'success': False,
                        'message': 'ضع وجهك داخل الإطار الأخضر',
                        'result': 'NO_FACE'
                    }), 400
            except Exception as e:
                print(f'[BOX_CHECK] error: {e}')
        else:
            # box_image غير مرسل (نسخة قديمة) — نمنع التسجيل
            print('[BOX_CHECK] no box_image received — blocking')
            if session_id:
                log_face_recognition_attempt(None, session_id, 'NO_FACE', 0.0, 'لم تُرسل صورة المربع')
            return jsonify({
                'success': False,
                'message': 'ضع وجهك داخل الإطار الأخضر',
                'result': 'NO_FACE'
            }), 400
        # ─────────────────────────────────────────────────────────────────────

        # ── الخطوة 2: التعرف على الوجه من الصورة الكاملة ────────────────────
        result = FaceRecognitionManager.recognize_face(
            image_data, enrolled_faces, threshold=threshold, is_base64=True
        )
        print(f'[TIMING] recognize: {time.time()-t2:.2f}s | total: {time.time()-t0:.2f}s | result: {result.get("result","?")}')
        # ─────────────────────────────────────────────────────────────────────
        
        # تسجيل المحاولة
        if session_id:
            log_face_recognition_attempt(
                result.get('student_id'),
                session_id,
                result.get('result', 'UNKNOWN'),
                result.get('confidence', 0.0),
                result.get('message')
            )
        
        if not result['success']:
            return jsonify(result), 400
        
        # تسجيل الحضور
        student_id = result['student_id']
        student = get_student_by_id(student_id)
        
        if not student:
            return jsonify({'success': False, 'message': 'خطأ: الطالب غير موجود'}), 500
        
        # محاولة تسجيل الحضور
        attendance_success = record_face_attendance(
            student_id,
            subject_id,
            student.get('group_name', ''),
            result['confidence'],
            session_id,
            method='FACE'
        )
        
        if not attendance_success:
            return jsonify({
                'success': False,
                'message': f'تم تسجيل حضور {student["full_name"]} مسبقاً اليوم',
                'student_id': student_id,
                'student_name': student['full_name'],
                'already_registered': True
            }), 400
        
        # نجاح كامل
        return jsonify({
            'success': True,
            'message': f'تم تسجيل حضور {student["full_name"]} بنجاح',
            'student_id': student_id,
            'student_name': student['full_name'],
            'student_code': student.get('student_code'),
            'grade': student.get('teacher_name'),
            'confidence': result['confidence'],
            'group_name': student.get('group_name')
        })
        
    except Exception as e:
        print(f'[Face Recognition Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/delete/<int:student_id>', methods=['POST'])
@login_required
def api_face_delete(student_id):
    """API: حذف بيانات الوجه للطالب"""
    try:
        from database import delete_student_face_data, get_student_by_id
        from face_recognition_utils import delete_face_image
        
        student = get_student_by_id(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'الطالب غير موجود'}), 404
        
        # حذف الصورة إن وجدت
        if student.get('face_image_path'):
            delete_face_image(student['face_image_path'])
        
        # حذف البيانات من قاعدة البيانات
        success = delete_student_face_data(student_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'تم حذف بيانات وجه {student["full_name"]}'
            })
        else:
            return jsonify({'success': False, 'message': 'فشل حذف بيانات الوجه'}), 500
            
    except Exception as e:
        print(f'[Face Delete Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/test/<int:student_id>', methods=['POST'])
@login_required
def api_face_test(student_id):
    """API: اختبار التعرف على وجه طالب محدد — يرجع distance للـ debug"""
    try:
        from face_recognition_utils import FaceRecognitionManager
        from database import get_student_by_id, get_student_face_encoding, get_face_recognition_settings
        
        data = request.get_json(force=True, silent=True)
        if not data or 'image_data' not in data:
            return jsonify({'success': False, 'message': 'الصورة مطلوبة'}), 400
        
        student = get_student_by_id(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'الطالب غير موجود'}), 404
        
        if not student.get('face_enrolled'):
            return jsonify({'success': False, 'message': 'الطالب لم يسجل وجهه بعد'}), 400
        
        # جلب encoding المسجل
        enrolled_encoding = get_student_face_encoding(student_id)
        if not enrolled_encoding:
            return jsonify({'success': False, 'message': 'بيانات الوجه غير موجودة'}), 404
        
        # نستخدم threshold عالي جداً عشان نشوف القيمة الفعلية دائماً
        enrolled_faces = [{
            'student_id': student_id,
            'name': student['full_name'],
            'face_encoding': enrolled_encoding
        }]
        
        result = FaceRecognitionManager.recognize_face(
            data['image_data'],
            enrolled_faces,
            threshold=999.0,  # threshold عالي جداً عشان نشوف الـ distance دائماً
            is_base64=True
        )
        
        # أضف threshold الحالي للمعلومات
        settings = get_face_recognition_settings()
        current_threshold = settings.get('recognition_threshold', 0.68)
        result['current_threshold'] = current_threshold
        result['would_match'] = result.get('distance', 999) <= current_threshold
        result['debug_info'] = f"distance={result.get('distance','N/A')}, threshold={current_threshold}"
        
        return jsonify(result)
        
    except Exception as e:
        print(f'[Face Test Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/session/create', methods=['POST'])
@login_required
def api_face_session_create():
    """API: إنشاء جلسة حضور بالوجه"""
    try:
        from database import create_face_attendance_session
        
        data = request.get_json(force=True, silent=True)
        if not data or 'subject_id' not in data:
            return jsonify({'success': False, 'message': 'معرف المادة مطلوب'}), 400
        
        try:
            subject_id = int(data['subject_id'])
            threshold = float(data.get('threshold', 0.6))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'معرف المادة أو عتبة التعرف غير صالحة'}), 400
        if not 0.5 <= threshold <= 0.9:
            return jsonify({'success': False, 'message': 'عتبة التعرف يجب أن تكون بين 0.5 و0.9'}), 400
        if not any(int(subject.get('id')) == subject_id for subject in get_all_subjects()):
            return jsonify({'success': False, 'message': 'المادة غير موجودة'}), 404
        session_name = str(data.get('session_name') or '').strip()[:120] or None
        
        # إنشاء الجلسة
        session_id = create_face_attendance_session(
            subject_id,
            session.get('user_id'),
            threshold,
            session_name
        )
        
        if session_id:
            return jsonify({
                'success': True,
                'session_id': session_id,
                'message': 'تم إنشاء جلسة الحضور'
            })
        else:
            return jsonify({'success': False, 'message': 'فشل إنشاء الجلسة'}), 500
            
    except Exception as e:
        print(f'[Face Session Create Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/session/close/<int:session_id>', methods=['POST'])
@login_required
def api_face_session_close(session_id):
    """API: إغلاق جلسة حضور بالوجه"""
    try:
        from database import close_face_attendance_session
        
        success = close_face_attendance_session(session_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'تم إغلاق الجلسة'
            })
        else:
            return jsonify({'success': False, 'message': 'فشل إغلاق الجلسة'}), 500
            
    except Exception as e:
        print(f'[Face Session Close Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/attendance/sync', methods=['POST'])
@login_required
def api_face_attendance_sync():
    """API: مزامنة سجلات حضور الوجه المحفوظة أوف لاين"""
    try:
        from database import record_face_attendance, create_face_attendance_session, get_active_face_session

        data = request.get_json(force=True, silent=True) or {}

        student_id  = data.get('student_id')
        subject_id  = data.get('subject_id')
        confidence  = data.get('confidence', 0.0)
        recorded_at = data.get('recorded_at', '')

        if not student_id or not subject_id:
            return jsonify({'success': False, 'message': 'بيانات ناقصة'}), 400

        try:
            student_id = int(student_id)
            subject_id = int(subject_id)
            confidence = float(confidence)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400

        from database import get_student_by_id
        student = get_student_by_id(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'الطالب غير موجود'}), 404

        group_name = student.get('group_name', 'غير معروف')

        active_session = get_active_face_session(subject_id)
        sess_id = active_session['id'] if active_session else None

        if not sess_id:
            sess_id = create_face_attendance_session(
                subject_id,
                session.get('user_id'),
                0.6,
                (f'مزامنة أوف لاين {recorded_at}')[:120]
            )

        saved = record_face_attendance(
            student_id, subject_id, group_name, confidence,
            session_id=sess_id, method='FACE'
        )

        if saved:
            return jsonify({'success': True, 'message': 'تم تسجيل الحضور'})
        return jsonify({'success': False, 'already_registered': True, 'message': 'مسجل مسبقاً'})

    except Exception as e:
        print(f'[Face Attendance Sync Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/descriptors')
@login_required
def api_face_descriptors():
    """API: جلب بيانات الطلاب المسجلين بصورهم (للتعرف في المتصفح بـ face-api.js)"""
    try:
        import base64 as _b64
        import os as _os

        BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))

        conn = database.get_db_connection()
        cursor = conn.cursor()

        # نتحقق أولاً إذا عمود face_image_data موجود
        has_image_data_col = False
        try:
            if database.IS_POSTGRES:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='students' AND column_name='face_image_data'")
                has_image_data_col = cursor.fetchone() is not None
            else:
                cursor.execute('PRAGMA table_info(students)')
                cols = {r['name'] for r in cursor.fetchall()}
                has_image_data_col = 'face_image_data' in cols
        except Exception as e:
            print(f'[Descriptors] Column check error: {e}')

        print(f'[Descriptors] has_image_data_col: {has_image_data_col}')

        if has_image_data_col:
            img_data_col = "face_image_data"
        else:
            img_data_col = "NULL as face_image_data"

        if database.IS_POSTGRES:
            cursor.execute(f'''
                SELECT id, full_name, student_code, group_name, face_image_path,
                       {img_data_col}
                FROM students
                WHERE face_enrolled = TRUE
            ''')
        else:
            cursor.execute(f'''
                SELECT id, full_name, student_code, group_name, face_image_path,
                       {img_data_col}
                FROM students
                WHERE face_enrolled = 1
            ''')
        rows = cursor.fetchall()
        print(f'[Descriptors] Found {len(rows)} enrolled students')

        if rows:
            # طباعة أول طالب للتشخيص
            sample = rows[0]
            print(f'[Descriptors] Sample student: id={sample.get("id")}, name={sample.get("full_name")}, has_image_data={bool(sample.get("face_image_data"))}')

        conn.close()

        students = []
        for row in rows:
            img_b64 = None

            # أولاً: من قاعدة البيانات (يبقى حتى بعد deployment)
            try:
                img_b64 = row['face_image_data'] if row.get('face_image_data') else None
            except Exception as e:
                print(f'[Descriptors] DB image read error for student {row.get("id")}: {e}')

            # ثانياً: من الملف (للبيئة المحلية)
            if not img_b64:
                face_path = row.get('face_image_path')
                if face_path:
                    candidates = [
                        face_path,
                        _os.path.join(BASE_DIR, face_path.lstrip('/')),
                        _os.path.join(BASE_DIR, 'instance', face_path.lstrip('/')),
                        _os.path.join(BASE_DIR, 'static', face_path.lstrip('/static/').lstrip('/')),
                    ]
                    for c in candidates:
                        if c and _os.path.isfile(c):
                            try:
                                with open(c, 'rb') as f:
                                    img_b64 = _b64.b64encode(f.read()).decode('utf-8')
                                print(f'[Descriptors] Loaded image from file for student {row.get("id")}')
                            except Exception as e:
                                print(f'[Descriptors] File read error: {e}')
                            break

            # إذا ما في صورة — أرجع رابط الصورة ليحملها الـ JS
            if not img_b64:
                print(f'[Descriptors] No image found for student {row.get("id")} — using fallback URL')

            face_image_url = url_for('api_face_image', student_id=row['id']) if row.get('face_image_path') else None

            students.append({
                'id': row['id'],
                'full_name': row['full_name'],
                'student_code': row.get('student_code', ''),
                'group_name': row.get('group_name', ''),
                'face_image_b64': img_b64,
                'face_image_url': face_image_url  # fallback للـ JS
            })

        print(f'[Descriptors] Returning {len(students)} students with images')
        return jsonify({'success': True, 'students': students, 'count': len(students), 'has_image_data_col': has_image_data_col})

    except Exception as e:
        print(f'[Face Descriptors Error] {e}')
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/face/stats')
@login_required
def api_face_stats():
    """API: إحصائيات Face Recognition"""
    try:
        from database import (
            get_all_students,
            get_students_without_face_enrollment,
            get_face_attendance_stats,
            get_face_recognition_logs
        )
        
        # إحصائيات عامة
        all_students = get_all_students()
        enrolled_students = [s for s in all_students if s.get('face_enrolled')]
        not_enrolled = get_students_without_face_enrollment()
        
        # إحصائيات اليوم
        today_stats = get_face_attendance_stats()
        
        # آخر محاولات
        recent_logs = get_face_recognition_logs(limit=20)
        
        return jsonify({
            'success': True,
            'total_students': len(all_students),
            'enrolled_students': len(enrolled_students),
            'not_enrolled_students': len(not_enrolled),
            'today_stats': today_stats,
            'recent_logs': recent_logs
        })
        
    except Exception as e:
        print(f'[Face Stats Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def api_face_settings():
    """API: جلب/حفظ إعدادات Face Recognition"""
    try:
        from database import get_face_recognition_settings, save_face_recognition_settings
        
        if request.method == 'GET':
            settings = get_face_recognition_settings()
            return jsonify({'success': True, 'settings': settings})
        
        else:  # POST
            data = request.get_json(force=True, silent=True)
            if not data:
                return jsonify({'success': False, 'message': 'بيانات غير صالحة'}), 400
            
            save_face_recognition_settings(
                threshold=data.get('threshold'),
                min_face_size=data.get('min_face_size'),
                save_logs=data.get('save_logs'),
                liveness=data.get('liveness'),
                cooldown=data.get('cooldown')
            )
            
            return jsonify({
                'success': True,
                'message': 'تم حفظ الإعدادات'
            })
            
    except Exception as e:
        print(f'[Face Settings Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/enrolled-students')
@login_required
def api_face_enrolled_students():
    """API: جلب قائمة الطلاب المسجلين"""
    try:
        from database import get_all_students

        all_students = get_all_students()
        print(f'[API] Total students from DB: {len(all_students)}')

        # استيراد الدالة بشكل آمن
        try:
            from face_recognition_utils import get_face_image_path
            face_utils_available = True
        except Exception as import_err:
            print(f'[API] face_recognition_utils unavailable: {import_err}')
            face_utils_available = False

        enrolled = []
        for s in all_students:
            face_img_url = None
            file_exists = False
            is_enrolled = bool(s.get('face_enrolled'))
            if is_enrolled and face_utils_available:
                actual_path = get_face_image_path(s.get('face_image_path'))
                if actual_path:
                    face_img_url = url_for('api_face_image', student_id=s['id'])
                    file_exists = True

            enrolled.append({
                'id': s['id'],
                'full_name': s['full_name'],
                'student_code': s['student_code'],
                'department': s.get('department'),
                'teacher_name': s.get('teacher_name'),
                'group_name': s.get('group_name'),
                'face_enrolled': is_enrolled,
                'face_file_exists': file_exists,
                'face_enrolled_at': s.get('face_enrolled_at'),
                'profile_image': s.get('profile_image'),
                'face_image_path': face_img_url
            })

        return jsonify({
            'success': True,
            'students': enrolled
        })

    except Exception as e:
        print(f'[Face Enrolled Students Error] {e}')
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@app.route('/api/face/image/<int:student_id>')
@login_required
def api_face_image(student_id):
    from face_recognition_utils import get_face_image_path

    student = get_student_by_id(student_id)
    if not student:
        return '', 404

    # صورة الوجه المسجلة فقط — بدون fallback للصورة الشخصية
    # (لتجنب عرض صورة طالب آخر بالخطأ)
    face_path = student.get('face_image_path') or ''
    if not face_path:
        return '', 404

    image_path = get_face_image_path(face_path)
    if not image_path:
        return '', 404

    response = send_file(image_path, mimetype='image/jpeg', conditional=True)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# ============================================
# SSE (Server-Sent Events) — مزامنة الحضور الفورية
# ============================================

_sse_clients = []       # قائمة (subject_id_or_None, Queue)
_sse_lock = threading.Lock()


def _notify_attendance_update(subject_id, data):
    """بث حدث حضور جديد لجميع الأساتذة المتصلين بنفس المادة أو بدون فلتر"""
    msg = json.dumps(data, ensure_ascii=False)
    with _sse_lock:
        dead = []
        for item in _sse_clients:
            client_subject, q = item
            if client_subject is None or str(client_subject) == str(subject_id):
                try:
                    q.put_nowait(msg)
                except _queue_module.Full:
                    dead.append(item)
        for item in dead:
            try:
                _sse_clients.remove(item)
            except ValueError:
                pass


@app.route('/api/attendance-stream')
@login_required
def attendance_stream():
    """SSE endpoint: يبث حدث حضور جديد للأستاذ المتصل"""
    subject_id = request.args.get('subject_id') or None
    q = _queue_module.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append((subject_id, q))

    def generate():
        try:
            yield 'data: {"type": "connected"}\n\n'
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f'data: {msg}\n\n'
                except _queue_module.Empty:
                    yield ': heartbeat\n\n'
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove((subject_id, q))
                except ValueError:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/latest-attendance')
@login_required
def latest_attendance():
    """API: أحدث سجلات الحضور (للـ polling الاحتياطي)"""
    subject_id = request.args.get('subject_id')
    limit = min(int(request.args.get('limit', 20)), 100)
    if subject_id:
        records = get_attendance_by_subject(int(subject_id))
    else:
        records = get_today_attendance_stats() or []
    result = [dict(r) for r in (records or [])[:limit]]
    return jsonify({'success': True, 'records': result, 'timestamp': datetime.now().isoformat()})


import threading as _ssl_thread
import os as _os


def _run_https():
    cert = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'cert.pem')
    key = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'key.pem')
    if _os.path.exists(cert) and _os.path.exists(key):
        print('[HTTPS] Running HTTPS on port 5443')
        app.run(host='0.0.0.0', port=5443, ssl_context=(cert, key), threaded=True, debug=False, use_reloader=False)
    else:
        print('[HTTPS] WARNING: cert.pem/key.pem not found - run generate_cert.py first')


# ============================================
# معالجة الأخطاء
# ============================================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'المسار غير موجود'}), 404
    return render_template('base.html'), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f'[500] {request.path}: {e}')
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'خطأ في الخادم'}), 500
    return render_template('base.html'), 500


@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'success': False, 'message': 'الملف كبير جداً (الحد الأقصى 8MB)'}), 413


if __name__ == '__main__':
    # تهيئة جداول Face Recognition
    try:
        from database import init_face_recognition_tables
        init_face_recognition_tables()
        print('[App] Face Recognition tables initialized')
    except Exception as e:
        print(f'[App] Face Recognition init warning: {e}')

    init_database()
    port = int(os.environ.get('PORT', 5000))
    # HTTP on port 5000 for local testing
    http_thread = _ssl_thread.Thread(
        target=lambda: app.run(host='0.0.0.0', port=port, threaded=True, debug=False, use_reloader=False),
        daemon=True,
        name='http-5000'
    )
    http_thread.start()
    # HTTPS on port 5443 for phones (camera requires Secure Context)
    _run_https()
