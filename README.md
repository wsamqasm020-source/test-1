# 🎓 نظام الحضور الذكي - QR + Face Recognition

<div align="center">

![Status](https://img.shields.io/badge/Status-Ready-brightgreen)
![Version](https://img.shields.io/badge/Version-1.0.0-blue)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

**نظام متكامل واحترافي لإدارة حضور الطلاب**

[البدء السريع](#-البدء-السريع) •
[المميزات](#-المميزات) •
[التوثيق](#-التوثيق) •
[الدعم](#-الدعم)

</div>

---

## 🎯 نظرة عامة

نظام حضور ذكي يدعم **طريقتين** للتسجيل:

### 📱 QR Code Attendance
- توليد QR فريد لكل طالب
- مسح سريع بالكاميرا
- يعمل بدون إنترنت (PWA)

### 🎭 Face Recognition Attendance ✨ جديد!
- **تعرف تلقائي** على الطلاب من الكاميرا
- **دقيق وآمن** - 6 آليات لمنع الأخطاء
- **سريع** - خلال ثوانٍ
- **سهل** - 3 خطوات فقط

---

## ⚡ البدء السريع

### 1️⃣ تثبيت المكتبات

```bash
pip install -r requirements.txt
```

**⏱️ الوقت المتوقع:** 5-15 دقيقة

انسخ `.env.example` إلى `.env`، ثم غيّر `FLASK_SECRET_KEY` و`INITIAL_ADMIN_PASSWORD` قبل أول تشغيل. يتطلب التعرف على الوجه تنزيل أوزان DeepFace عند أول استخدام.

### 2️⃣ تشغيل التطبيق

```bash
python app.py
```

ثم افتح: **http://localhost:5000**

### 3️⃣ استخدام النظام

1. **سجل دخول** كمدرس
2. **سجل وجه طالب:**
   - إدارة الوجوه → تسجيل → كاميرا/رفع صورة ✅
3. **سجل حضور:**
   - حضور بالوجه → اختر المادة → بدء جلسة 🎉

---

## ✨ المميزات

### 🎭 Face Recognition
- ✅ تسجيل الوجه (كاميرا + رفع صورة)
- ✅ تعرف تلقائي سريع (1-3 ثواني)
- ✅ منع الأخطاء (Confidence + Quality checks)
- ✅ منع التكرار (لا حضور مرتين)
- ✅ وضعان: تلقائي (Classroom) + يدوي (Manual)
- ✅ إحصائيات وتقارير شاملة
- ✅ آمن (Face Embeddings فقط)

### 📱 QR Code
- ✅ توليد QR فريد
- ✅ مسح سريع
- ✅ يعمل بدون إنترنت
- ✅ جلسات آمنة

### 🎓 إدارة شاملة
- ✅ إدارة الطلاب والمواد
- ✅ سجلات حضور تفصيلية
- ✅ نظام درجات
- ✅ تقارير وإحصائيات
- ✅ PWA - يعمل كتطبيق

---

## 📚 التوثيق

### للبدء:
| المستند | الوصف | الأولوية |
|---------|-------|----------|
| [**START_HERE.md**](START_HERE.md) | ابدأ خلال 3 خطوات | ⭐⭐⭐ |
| [**QUICK_START_FACE.md**](QUICK_START_FACE.md) | دليل البدء السريع | ⭐⭐⭐ |
| [**USER_GUIDE.md**](USER_GUIDE.md) | دليل المستخدم الكامل | ⭐⭐ |

### للفهم العميق:
| المستند | الوصف |
|---------|-------|
| [**README_COMPLETE.md**](README_COMPLETE.md) | دليل شامل موحد |
| [**FACE_RECOGNITION_README.md**](FACE_RECOGNITION_README.md) | توثيق تفصيلي |
| [**STATUS_REPORT.md**](STATUS_REPORT.md) | تقرير حالة المشروع |
| [**FILE_INDEX.md**](FILE_INDEX.md) | فهرس جميع الملفات |

### عند المشاكل:
| المستند | الوصف |
|---------|-------|
| [**TROUBLESHOOTING.md**](TROUBLESHOOTING.md) | حلول لجميع المشاكل |

---

## 🛠️ سكريبتات مساعدة

```bash
# تهيئة تلقائية شاملة
python setup_face_recognition.py

# اختبار سريع
python test_face_recognition.py

# فحص شامل (50+ شيء)
python final_check.py
```

---

## 📊 التقنيات المستخدمة

### Backend
- **Python** 3.11+
- **Flask** - Web Framework
- **DeepFace (Facenet512)** - التعرف على الوجه
- **OpenCV** - معالجة الصور
- **SQLite/PostgreSQL** - قاعدة البيانات

### Frontend
- **HTML5** + **CSS3** + **JavaScript**
- **Bootstrap 5** - واجهة احترافية
- **Camera API** - الوصول للكاميرا
- **PWA** - تطبيق ويب تقدمي

---

## 🗂️ هيكل المشروع

```
📦 تعديلات قاسم/
├── 🐍 Backend
│   ├── app.py                        # التطبيق الرئيسي
│   ├── database.py                   # قاعدة البيانات
│   ├── face_recognition_utils.py     # محرك Face Recognition
│   └── ...
│
├── 📄 Frontend
│   ├── templates/
│   │   ├── face_attendance.html      # الحضور بالوجه
│   │   ├── face_management.html      # إدارة الوجوه
│   │   └── ...
│   └── static/
│       ├── css/
│       ├── js/
│       └── icons/
│
├── 📚 Documentation
│   ├── README.md                     # هذا الملف
│   ├── START_HERE.md                 # ابدأ هنا
│   ├── USER_GUIDE.md                 # دليل المستخدم
│   └── ...
│
├── 🗄️ Database
│   └── attendance.db                 # قاعدة البيانات
│
└── 🔒 Private biometric images
    └── instance/face_images/         # صور الوجوه خارج static
```

---

## 🎨 لقطات الشاشة

### صفحة الحضور بالوجه
```
┌─────────────────────────────────────────────────┐
│  📷 Face Attendance                            │
│  ┌───────────────────────────────────────┐    │
│  │                                       │    │
│  │       [إطار الكاميرا المباشر]        │    │
│  │                                       │    │
│  └───────────────────────────────────────┘    │
│                                                │
│  المادة: [اختر المادة ▼]                      │
│  دقة التعرف: [▓▓▓▓▓░░░░░] 60%              │
│  الوضع: [⚡ Classroom Mode]                   │
│                                                │
│  [🚀 بدء جلسة الحضور]                        │
│                                                │
│  📊 الإحصائيات:                               │
│  ✅ حاضرين: 15  |  🔄 محاولات: 17            │
└─────────────────────────────────────────────────┘
```

### صفحة إدارة الوجوه
```
┌─────────────────────────────────────────────────┐
│  ⚙️  إدارة الوجوه                              │
│  🔍 [ابحث عن طالب...]                         │
│                                                │
│  ┌─────────────────────────────────────────┐  │
│  │ الاسم     │ القسم    │ الحالة  │ إجراءات │  │
│  ├─────────────────────────────────────────┤  │
│  │ محمد أحمد │ السادس   │ ✅ مسجل │ [تحديث] │  │
│  │ أحمد علي  │ الخامس   │ ❌ غير  │ [تسجيل] │  │
│  │ ...       │ ...       │ ...     │ [اختبار]│  │
│  └─────────────────────────────────────────┘  │
│                                                │
│  📊 الإجمالي: 120 طالب | مسجلين: 85 (71%)   │
└─────────────────────────────────────────────────┘
```

---

## 🔒 الأمان والخصوصية

- ✅ **صور الوجوه مخزنة خارج static** ولا تُعرض إلا للمستخدمين المسجلين
- ✅ **Face Embeddings** مخزنة في قاعدة البيانات
- ✅ **صلاحيات محكمة** - Admin/Teacher/Student
- ✅ **HTTPS موصى به** للإنتاج
- ✅ **GDPR Compliant** - حماية الخصوصية
- ✅ **حذف تلقائي** للصور المؤقتة

---

## ⚙️ المتطلبات

### البرمجيات:
- Python 3.11+
- pip (مدير حزم Python)
- كاميرا (للـ Face Recognition)
- متصفح حديث (Chrome, Firefox, Edge)

### المكتبات الرئيسية:
راجع `requirements.txt` لقائمة الإصدارات المثبتة والمختبرة.

---

## 🚀 النشر (Deployment)

### محلياً (Local)
```bash
python app.py
```

### Heroku
```bash
git push heroku main
```

### Railway
```bash
railway up
```

> 💡 **ملاحظة:** قد يستغرق تنزيل أوزان DeepFace وقتاً عند أول تشغيل للتعرف على الوجه.

---

## 🐛 استكشاف الأخطاء

### المشاكل الشائعة:

| المشكلة | الحل |
|---------|------|
| فشل تثبيت DeepFace أو تنزيل الأوزان | تحقق من توافق Python والاتصال بالشبكة |
| فشل فتح الكاميرا | تحقق من الأذونات + HTTPS |
| لم يتم التعرف عليك | حسّن الإضاءة + خفض الدقة |
| تم تسجيل حضورك مسبقاً | هذا صحيح - النظام يمنع التكرار |

📖 **للمزيد:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 📞 الدعم والمساعدة

### المصادر:
1. **التوثيق:** راجع الملفات أعلاه
2. **الأسئلة الشائعة:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
3. **دليل المستخدم:** [USER_GUIDE.md](USER_GUIDE.md)

### التواصل:
- 📧 Email: [قاسم وسام]
- 💬 Issues: [GitHub/GitLab]
- 📖 Docs: هذا المشروع

---

## 🎯 خريطة الطريق (Roadmap)

### الإصدار الحالي (v1.0.0) ✅
- ✅ Face Recognition كامل
- ✅ QR Code Attendance
- ✅ إدارة شاملة
- ✅ توثيق كامل

### الإصدار القادم (v1.1.0) 🔜
- [ ] Multi-Image Enrollment
- [ ] Advanced Liveness Detection
- [ ] Batch Operations
- [ ] Excel Export/Import

### المستقبل (v2.0.0) 🔮
- [ ] Mobile App (Android/iOS)
- [ ] Face Mask Detection
- [ ] Offline Mode (كامل)
- [ ] Cloud Sync
- [ ] Multi-Camera Support

---

## 🤝 المساهمة

نرحب بالمساهمات! إذا كنت تريد المساهمة:

1. Fork المشروع
2. أنشئ Branch جديد (`git checkout -b feature/amazing`)
3. Commit تغييراتك (`git commit -m 'Add amazing feature'`)
4. Push للـ Branch (`git push origin feature/amazing`)
5. افتح Pull Request

---

## 📜 الترخيص

هذا المشروع مرخص تحت [MIT License](LICENSE).

---

## 🙏 شكر وتقدير

### المكتبات المستخدمة:
- **face_recognition** by Adam Geitgey
- **OpenCV** - Computer Vision Library
- **dlib** by Davis King
- **Flask** - Web Framework
- **Bootstrap** - UI Framework

---

## 📊 الإحصائيات

![GitHub code size](https://img.shields.io/badge/Code%20Size-200KB+-blue)
![GitHub docs size](https://img.shields.io/badge/Docs%20Size-80KB+-green)
![Features](https://img.shields.io/badge/Features-20%2F20-brightgreen)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success)

---

## 🌐 إعداد الشبكة المحلية (LAN)

لتشغيل النظام على شبكة Wi-Fi محلية بحيث يتصل الطلاب من هواتفهم:

### التشغيل السريع
```bat
START_LAN.bat
```

### العناوين بعد التشغيل
| الاستخدام | العنوان |
|-----------|---------|
| HTTP (بدون كاميرا مباشرة) | `http://192.168.0.190:5000` |
| HTTPS (مع الكاميرا) | `https://192.168.0.190:5443` |

> استبدل `192.168.0.190` بعنوان IP حاسوبك الفعلي (يظهر في START_LAN.bat تلقائياً).

### إعداد HTTPS للكاميرا (مرة واحدة)
```bash
python generate_cert.py
```
ثم ثبّت الشهادة على هواتف الطلاب — راجع **INSTALL_CERT.md**.

### إعداد جدار الحماية
```powershell
# شغّل كـ Administrator
New-NetFirewallRule -DisplayName 'Attendance HTTP LAN' -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
New-NetFirewallRule -DisplayName 'Attendance HTTPS LAN' -Direction Inbound -Protocol TCP -LocalPort 5443 -Action Allow -Profile Private
```

للتفاصيل الكاملة: [LAN_SETUP_REPORT.md](LAN_SETUP_REPORT.md)

---

<div align="center">

## 🎉 جاهز للاستخدام!

**3 خطوات فقط:**

```bash
pip install -r requirements.txt
python app.py
# افتح http://localhost:5000
```

**اقرأ:** [START_HERE.md](START_HERE.md) للبدء خلال 3 خطوات

---

**Made with ❤️ by قاسم وسام**

**2026**

</div>
