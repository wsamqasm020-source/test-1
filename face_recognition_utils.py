"""
نظام التعرف على الوجوه — OpenCV سريع
بدون مكتبات خارجية ثقيلة
"""

import cv2
import numpy as np
import base64
import os

__version__ = "8.0.0-fast"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FACES_DIR = os.path.join(_BASE_DIR, 'static', 'uploads', 'faces')
os.makedirs(_FACES_DIR, exist_ok=True)

_CASCADE_PATH = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
_face_cascade = cv2.CascadeClassifier(_CASCADE_PATH)

print(f"[Face Recognition] ✅ OpenCV {cv2.__version__} — Fast mode v8")


def _base64_to_bgr(image_data: str):
    """تحويل base64 لصورة BGR — بدون PIL (أسرع)"""
    if ',' in image_data:
        image_data = image_data.split(',')[1]
    raw = base64.b64decode(image_data)
    arr = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("تعذّر فك ضغط الصورة")
    return bgr


def _detect_face(bgr_img, min_face_ratio=0.10):
    """كشف أكبر وجه — يرجع (x,y,w,h) أو None"""
    h, w = bgr_img.shape[:2]
    # resize للكشف السريع — نحافظ على حد أدنى 160px
    scale = min(1.0, 320 / max(w, h))
    sw, sh = max(int(w*scale), 1), max(int(h*scale), 1)
    small = cv2.resize(bgr_img, (sw, sh)) if scale < 1 else bgr_img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    cv2.equalizeHist(gray, gray)

    # minSize يعتمد على حجم الصورة المصغرة (10% من أقل بُعد)
    min_dim = max(int(min(sw, sh) * min_face_ratio), 20)

    faces = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4,
        minSize=(min_dim, min_dim), flags=cv2.CASCADE_SCALE_IMAGE
    )
    if len(faces) == 0:
        return None
    fx, fy, fw, fh = max(faces, key=lambda f: f[2]*f[3])
    # إرجاع الإحداثيات بالحجم الأصلي
    inv = 1.0 / scale
    return (int(fx*inv), int(fy*inv), int(fw*inv), int(fh*inv))


def _crop_and_encode(bgr_img, face_rect, size=48):
    """قص الوجه واستخراج features سريعة"""
    x, y, w, h = face_rect
    mg = int(min(w, h) * 0.10)
    x1 = max(0, x - mg)
    y1 = max(0, y - mg)
    x2 = min(bgr_img.shape[1], x + w + mg)
    y2 = min(bgr_img.shape[0], y + h + mg)
    face = bgr_img[y1:y2, x1:x2]
    if face.size == 0:
        return None
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    cv2.equalizeHist(gray, gray)
    resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    vec = resized.flatten().astype(np.float32) / 255.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _enc_to_b64(arr: np.ndarray) -> str:
    return base64.b64encode(arr.astype(np.float32).tobytes()).decode()


def _b64_to_enc(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float32)


def _cosine(a, b):
    return float(np.dot(a, b))


def _quality_check(bgr_img):
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    b = float(np.mean(gray))
    if b < 20:
        return False, "الصورة مظلمة جداً"
    if b > 252:
        return False, "الصورة ساطعة جداً"
    return True, "جيد"


class FaceRecognitionManager:
    # threshold لـ cosine similarity (0-1) — أعلى = أدق
    DEFAULT_CONFIDENCE_THRESHOLD = 0.80

    @staticmethod
    def enroll_face(image_data, is_base64=True):
        try:
            bgr = _base64_to_bgr(image_data) if is_base64 else image_data

            ok, msg = _quality_check(bgr)
            if not ok:
                return {'success': False, 'message': msg}

            face_rect = _detect_face(bgr)

            if face_rect is not None:
                h, w = bgr.shape[:2]
                fx, fy, fw, fh = face_rect
                if (fw * fh) / (w * h) < 0.01:
                    face_rect = None  # الوجه صغير جداً — استخدم الصورة كاملة

            if face_rect is not None:
                features = _crop_and_encode(bgr, face_rect)
            else:
                # لم يُكتشف وجه — استخدم الصورة كاملة كـ fallback
                h, w = bgr.shape[:2]
                face_rect = (0, 0, w, h)
                features = _crop_and_encode(bgr, face_rect)

            if features is None:
                return {'success': False, 'message': 'تعذّر معالجة الصورة'}

            return {
                'success': True,
                'face_encoding': _enc_to_b64(features),
                'quality': 'جيد' if _detect_face(bgr) is not None else 'مقبول',
            }

        except Exception as e:
            print(f'[FRM.enroll_face] {e}')
            return {'success': False, 'message': f'خطأ: {e}'}

    @staticmethod
    def recognize_face(image_data, enrolled_faces, threshold=None, is_base64=True):
        if threshold is None:
            threshold = FaceRecognitionManager.DEFAULT_CONFIDENCE_THRESHOLD
        if threshold > 1.0 or threshold < 0.1:
            threshold = FaceRecognitionManager.DEFAULT_CONFIDENCE_THRESHOLD

        try:
            bgr = _base64_to_bgr(image_data) if is_base64 else image_data

            img_h, img_w = bgr.shape[:2]
            face_rect = _detect_face(bgr)
            if face_rect is None:
                return {
                    'success': False,
                    'message': 'لم يتم اكتشاف أي وجه في الإطار — يرجى التأكد من وجود الوجه أمام الكاميرا',
                    'result': 'NO_FACE',
                    'face_rect': None,
                    'img_size': (img_w, img_h)
                }

            input_vec = _crop_and_encode(bgr, face_rect)
            if input_vec is None:
                return {'success': False, 'message': 'تعذّر معالجة الوجه', 'result': 'ERROR'}

            expected_len = input_vec.shape[0]  # 48*48 = 2304
            best_sim = -1.0
            best_face = None

            for face in enrolled_faces:
                enc_str = face.get('face_encoding')  # استخدم face_encoding فقط
                if not enc_str:
                    continue
                try:
                    known = _b64_to_enc(enc_str)
                    if known.shape[0] != expected_len:
                        continue
                    sim = _cosine(input_vec, known)
                    if sim > best_sim:
                        best_sim = sim
                        best_face = face
                except Exception:
                    continue

            if best_face is None:
                return {
                    'success': False,
                    'message': 'لا يوجد وجوه مسجلة — سجّل الوجوه أولاً',
                    'result': 'UNKNOWN'
                }

            print(f'[Face] student={best_face.get("student_id")} sim={best_sim:.3f} thr={threshold} → {"MATCH" if best_sim>=threshold else "NO"}')

            if best_sim < threshold:
                return {
                    'success': False,
                    'message': f'الوجه غير معروف (sim={best_sim:.3f})',
                    'result': 'UNKNOWN',
                    'confidence': round(best_sim, 3),
                    'distance': round(1.0 - best_sim, 4),
                }

            return {
                'success': True,
                'result': 'SUCCESS',
                'student_id': best_face['student_id'],
                'name': best_face.get('name', ''),
                'confidence': round(best_sim, 3),
                'distance': round(1.0 - best_sim, 4),
                'face_rect': face_rect,
                'img_size': (img_w, img_h),
            }

        except Exception as e:
            print(f'[FRM.recognize_face] {e}')
            return {'success': False, 'message': f'خطأ: {e}', 'result': 'ERROR'}

    @staticmethod
    def check_quality(image_data, is_base64=True):
        try:
            bgr = _base64_to_bgr(image_data) if is_base64 else image_data
            ok, msg = _quality_check(bgr)
            return {'ok': ok, 'message': msg}
        except Exception as e:
            return {'ok': False, 'message': str(e)}

    @staticmethod
    def detect_faces(image_data, is_base64=True):
        try:
            bgr = _base64_to_bgr(image_data) if is_base64 else image_data
            rect = _detect_face(bgr)
            return [rect] if rect else []
        except Exception:
            return []


def save_face_image(image_data: str, student_id: int):
    try:
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        raw = base64.b64decode(image_data)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        filename = f'face_{student_id}.jpg'
        full_path = os.path.join(_FACES_DIR, filename)
        # cv2.imwrite يفشل مع مسارات Unicode على Windows
        # نستخدم imencode + open() بدلاً منه
        ret, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            return None
        with open(full_path, 'wb') as f:
            f.write(buf.tobytes())
        if not os.path.isfile(full_path):
            return None
        return f'/static/uploads/faces/{filename}'
    except Exception as e:
        print(f'[save_face_image] {e}')
        return None


def delete_face_image(image_path: str) -> bool:
    try:
        if not image_path:
            return False
        full = os.path.join(_BASE_DIR, image_path.lstrip('/'))
        if os.path.isfile(full):
            os.remove(full)
            return True
    except Exception as e:
        print(f'[delete_face_image] {e}')
    return False


def get_face_image_path(image_path: str):
    """يُرجع المسار الكامل للصورة إذا موجودة"""
    if not image_path:
        return None
    full = os.path.join(_BASE_DIR, image_path.lstrip('/'))
    if os.path.isfile(full):
        return full
    if os.path.isfile(image_path):
        return image_path
    return None
