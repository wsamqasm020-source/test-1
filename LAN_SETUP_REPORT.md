# تقرير إعداد نظام الحضور على الشبكة المحلية (LAN)

## تاريخ الإعداد
2026-10-13

## تقنية المشروع
- الإطار: Flask 3.0
- اللغة: Python 3.11
- قاعدة البيانات: SQLite (attendance.db) في جذر المشروع
- نظام التشغيل: Windows

## ملفات قاعدة البيانات
- الملف الرئيسي: `c:\Projects\pwa\attendance.db`
- النسخة الاحتياطية: `c:\Projects\pwa\attendance.db.backup`

## الملفات المعدّلة
1. **app.py** — تعديل app.run لاستماع على 0.0.0.0، إضافة HTTP+HTTPS (منفذان 5000 و 5443)، إضافة SSE endpoint، CORS للشبكة المحلية فقط، error handlers (404/500/413)
2. **database.py** — إضافة WAL mode، busy_timeout=5000، synchronous=NORMAL، check_same_thread=False، UNIQUE INDEX على attendance
3. **templates/base.html** — استبدال Google Fonts CDN بملف خط Cairo محلي
4. **templates/attendance.html** — إضافة SSE JavaScript للتحديث الفوري لواجهة الأستاذ
5. **templates/student_scan.html** — fallback لكاميرا الهاتف عند HTTP (بدون Secure Context)

## الملفات المضافة
| الملف | الوظيفة |
|-------|----------|
| `START_LAN.bat` | تشغيل الخادم مع عرض IP محلي والمنفذين 5000 و 5443 |
| `generate_cert.py` | توليد شهادة SSL self-signed لـ HTTPS |
| `cert.pem` | شهادة SSL (بعد تشغيل generate_cert.py) |
| `key.pem` | مفتاح SSL (بعد تشغيل generate_cert.py) |
| `INSTALL_CERT.md` | خطوات تثبيت الشهادة على هواتف الطلاب |
| `static/fonts/cairo.css` | خط Cairo العربي محلي بديل Google Fonts |
| `lan_sync.py` | Blueprint لمزامنة البيانات على الشبكة المحلية |
| `app.py.backup` | نسخة احتياطية من app.py |
| `database.py.backup` | نسخة احتياطية من database.py |

---

## طريقة التشغيل

### الخطوة الأولى (مرة واحدة فقط): توليد شهادة SSL
```
python generate_cert.py
```
هذا ينشئ `cert.pem` و `key.pem` مربوطين بعنوان IP الحاسوب الحالي.

### تشغيل الخادم
انقر مزدوجاً على **START_LAN.bat** أو من سطر الأوامر:
```
cd c:\Projects\pwa
python app.py
```

---

## العناوين

| البروتوكول | العنوان | الاستخدام |
|------------|---------|-----------|
| HTTP محلي | http://127.0.0.1:5000 | اختبار محلي فقط |
| HTTP شبكة | http://192.168.0.190:5000 | الوصول من الهواتف (بدون كاميرا مباشرة) |
| HTTPS شبكة | https://192.168.0.190:5443 | **الكاميرا + جميع الميزات** |

**عنوان IP الفعلي للحاسوب:** `192.168.0.190` (من Wi-Fi)

---

## اتصال الطلاب بالشبكة
يجب أن يكون الطالب متصلاً بـ **Wi-Fi نفسه** الذي يستخدمه الحاسوب.

لتفعيل الكاميرا على الهاتف، يجب استخدام **HTTPS**:
```
https://192.168.0.190:5443
```

على HTTP يعمل النظام كاملاً ماعدا الكاميرا المباشرة — سيظهر بدلاً عنها زر رفع صورة QR.

---

## إعداد جدار الحماية (Windows Firewall)
شغّل بصلاحيات **Administrator** في PowerShell:
```powershell
New-NetFirewallRule -DisplayName 'Attendance HTTP LAN' -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
New-NetFirewallRule -DisplayName 'Attendance HTTPS LAN' -Direction Inbound -Protocol TCP -LocalPort 5443 -Action Allow -Profile Private
```
هذا يفتح المنفذين على الشبكة الخاصة فقط ولا يكشفهما للإنترنت.

---

## تثبيت شهادة SSL على هواتف الطلاب
راجع: **INSTALL_CERT.md**

الخطوة الأساسية: نسخ `cert.pem` إلى هاتف الطالب وتثبيته كـ "User Certificate" أو "CA Certificate" من إعدادات الأمان.

---

## التشغيل التلقائي عند بدء Windows
1. اضغط `Win+R` ثم اكتب: `shell:startup`
2. أنشئ اختصاراً لـ `START_LAN.bat` في المجلد الذي يفتح

---

## استعادة النسخة الاحتياطية
إذا حدث خطأ في أي ملف:
```bat
copy c:\Projects\pwa\app.py.backup c:\Projects\pwa\app.py
copy c:\Projects\pwa\database.py.backup c:\Projects\pwa\database.py
copy c:\Projects\pwa\attendance.db.backup c:\Projects\pwa\attendance.db
```

---

## نتائج الاختبار

| الاختبار | النتيجة |
|----------|----------|
| `py_compile app.py` | ✅ نجح — لا أخطاء syntax |
| `py_compile database.py` | ✅ نجح — لا أخطاء syntax |
| `py_compile lan_sync.py` | ✅ نجح — لا أخطاء syntax |
| تشغيل الخادم (`app.py`) | ✅ يعمل — HTTP + HTTPS |
| `GET http://127.0.0.1:5000/` | ✅ HTTP 200 |
| HTTP على الشبكة | ✅ يعمل على `http://192.168.0.190:5000` |
| HTTPS على الشبكة | ✅ يعمل على `https://192.168.0.190:5443` |
| استيراد database | ✅ DB imports OK |
| WAL mode | ✅ journal_mode=wal، busy_timeout=5000 |
| SSE endpoint | ✅ `/api/attendance-stream` مضاف، تحديث فوري في واجهة الأستاذ |
| خط Cairo محلي | ✅ `static/fonts/cairo.css` — لا يحتاج إنترنت |
| CORS للشبكة المحلية | ✅ يسمح فقط من 192.168.x.x / 10.x.x.x / 172.x.x.x |

---

## ميزات لا تعمل بدون إنترنت

| الميزة | الحالة |
|--------|--------|
| خط Cairo (Google Fonts) | ✅ تم نقله محلياً |
| Bootstrap + FontAwesome | ✅ موجودان محلياً في `static/` |
| html5-qrcode.min.js | ✅ موجود محلياً في `static/js/` |
| face-api.min.js | ✅ موجود محلياً في `static/js/` |
| تسجيل الحضور (SQLite) | ✅ يعمل محلياً بدون إنترنت |
| بوابة الطالب والمدرس | ✅ تعمل محلياً بدون إنترنت |

---

## ملاحظات هامة
- لا تحذف `cert.pem` و `key.pem` بعد إنشائهما
- إذا تغيّر IP الحاسوب (تغيير الراوتر أو إعادة تعيين DHCP)، شغّل `generate_cert.py` مجدداً وأعد تثبيت الشهادة على الهواتف
- لتثبيت IP ثابت: يُفضّل إعداد DHCP Reservation في إعدادات الراوتر باستخدام MAC address الحاسوب
- يدعم الخادم طلبات متزامنة من عدة طلاب في آنٍ واحد (threaded=True)
- عند انقطاع اتصال SSE، يعيد المتصفح الاتصال تلقائياً مع backoff تدريجي
