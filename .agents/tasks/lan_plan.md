# خطة التنفيذ: تطوير نظام الحضور للعمل على الشبكة المحلية (LAN)

---

## ملخص نتائج الفحص

### بنية المشروع
- **الإطار**: Flask 3.0 / Python (تطبيق WSGI)
- **قاعدة البيانات**: SQLite (`attendance.db` في جذر المشروع) — بدون WAL mode، بدون UNIQUE constraint على جدول attendance
- **البيئة الافتراضية**: `c:\Projects\pwa\venv\`
- **ملف التشغيل الحالي**: `app.py` — سطر `app.run()` في الأسفل (السطر 2677):
  ```python
  app.run(debug=debug, host='0.0.0.0', port=port)
  ```
  حيث `port = int(os.environ.get('PORT', 5000))` — الخادم يستمع بالفعل على `0.0.0.0:5000`، إذن إمكانية الوصول من الشبكة المحلية **موجودة مبدئياً**.

### CDN الخارجية الموجودة (روابط تنكسر بدون إنترنت)

| الملف | الرابط الخارجي |
|-------|--------------|
| `base.html` | `https://fonts.googleapis.com/css2?family=Cairo...` (غير حرجة — لها fallback محلي في CSS) |
| `base.html` | `https://cdn.jsdelivr.net/npm/sweetalert2@11` (**حرجة** — تُستخدم في كل الصفحات) |
| `student_scan.html` | `https://cdnjs.cloudflare.com/libs/font-awesome/6.4.2/css/all.min.css` (**حرجة**) |
| `student_scan.html` | `https://fonts.googleapis.com/css2?family=Cairo...` |
| `student_settings.html` | `https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.rtl.min.css` (**حرجة**) |
| `student_settings.html` | `https://cdnjs.cloudflare.com/libs/font-awesome/6.4.2/css/all.min.css` (**حرجة**) |
| `student_settings.html` | `https://fonts.googleapis.com/css2?family=Cairo...` |
| `student_settings.html` | `https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js` (**حرجة**) |
| `unified_login.html` | `https://fonts.googleapis.com/css2?family=Cairo...` |
| `unified_login.html` | `https://cdnjs.cloudflare.com/libs/font-awesome/6.4.0/css/all.min.css` (**حرجة**) |
| `network.html` | `https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js` (**حرجة**) |

**الملفات المحلية الموجودة بالفعل في `static/`:**
- `static/css/bootstrap.min.css` ← Bootstrap موجود محلياً
- `static/css/font-awesome.min.css` ← Font Awesome موجود محلياً
- `static/js/bootstrap.bundle.min.js` ← Bootstrap JS موجود محلياً
- `static/js/html5-qrcode.min.js` ← html5-qrcode موجود محلياً
- `static/js/app.js` ← منطق offline موجود محلياً

### طريقة تحديث واجهة الأستاذ
- **`attendance.html`**: polling يدوي فقط — لا يوجد auto-refresh تلقائي. الأستاذ يضغط زر "عرض" يدوياً.
- **`face_dashboard.html`**: polling تلقائي كل 30 ثانية عبر `setInterval`.
- **لا يوجد SSE أو WebSocket** في أي مكان.

### آلية منع التكرار في قاعدة البيانات
- `record_attendance()` في `database.py` يستخدم `BEGIN IMMEDIATE` + فحص `SELECT` + `INSERT` — يمنع التكرار لكنه **يعتمد على logic لا على UNIQUE constraint** في جدول `attendance`.
- لا يوجد `UNIQUE (student_id, subject_id, attendance_date)` في تعريف الجدول.

### WAL Mode
- **غائب تماماً** — `get_db_connection()` يفتح SQLite بدون `PRAGMA journal_mode=WAL`، مما يخلق مشكلة عند الطلبات المتزامنة من عدة طلاب.

### الكاميرا وسياق الأمان
- `student_scan.html` يفحص `isSecureContext` ويعرض رسالة مناسبة إذا كان HTTP.
- `Html5Qrcode` يستخدم `getUserMedia` — **لن تعمل الكاميرا المباشرة على HTTP** من هواتف Android Chrome أو iOS Safari.
- الحل الجاهز في الكود: زر "التقاط صورة QR" (`<input type="file" accept="image/*" capture="environment">`) — هذا **يعمل على HTTP** لأنه يفتح كاميرا النظام دون `getUserMedia`.

---

## خطة التنفيذ

### الخطوة 1: تفعيل WAL mode وإضافة UNIQUE constraint على جدول attendance

**ما يتغير:**
1. في `database.py` — دالة `get_db_connection()`: أضف بعد `conn.row_factory = sqlite3.Row` سطرين:
   ```python
   conn.execute('PRAGMA journal_mode=WAL')
   conn.execute('PRAGMA busy_timeout=5000')
   ```
2. في `database.py` — دالة `init_database()`: أضف migration بعد إنشاء الجدول لإضافة UNIQUE constraint:
   ```python
   # Migration: إضافة UNIQUE constraint على attendance إن لم تكن موجودة
   try:
       cursor.execute('''
           CREATE UNIQUE INDEX IF NOT EXISTS uix_attendance_student_subject_date
           ON attendance (student_id, subject_id, attendance_date)
       ''')
       conn.commit()
   except Exception as e:
       print(f'[DB Migration] attendance unique index: {e}')
   ```
   ملاحظة: `CREATE UNIQUE INDEX IF NOT EXISTS` آمن — يتخطى إذا كان موجوداً، ويفشل بهدوء إذا كان هناك بيانات مكررة قديمة.

**الملفات:** `database.py`

**التحقق:** شغّل `python -c "from database import get_db_connection; conn = get_db_connection(); print(conn.execute('PRAGMA journal_mode').fetchone()[0])"` — النتيجة المتوقعة: `wal`.

---

### الخطوة 2: تأكيد تشغيل الخادم على 0.0.0.0 وتحديد العنوان الفعلي

**الخادم بالفعل يستمع على `host='0.0.0.0'`** — لا تغيير مطلوب في `app.py`.

**ما يتغير:** إنشاء ملف `.env` (نسخة من `.env.example`) مع إضافة `PORT=5000` صريحة إذا لم يكن موجوداً.

**إجراء يدوي للمستخدم (لا يمكن أتمتته):**
> لمعرفة عنوان الحاسوب على الشبكة:
> ```
> ipconfig
> ```
> ابحث عن قسم "Wireless LAN adapter Wi-Fi" أو "Ethernet adapter" وخذ قيمة "IPv4 Address" — مثال: `192.168.1.100`.
> هذا هو الرابط الذي يستخدمه الطلاب: `http://192.168.1.100:5000`

**الملفات:** لا تغيير في الكود — فقط توثيق في `README.md` أو `RUN_SERVER.bat`

---

### الخطوة 3: قواعد جدار الحماية Windows Firewall

**ما يتغير:** إنشاء سكربت PowerShell جديد `setup_firewall.ps1` لإضافة قاعدة firewall لمنفذ 5000 على الشبكة الخاصة فقط.

**محتوى السكربت:**
```powershell
# يجب تشغيله كـ Administrator
$ruleName = "QR-Attendance-Flask-5000"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "[✓] القاعدة موجودة بالفعل: $ruleName"
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 5000 `
        -Action Allow `
        -Profile Private `
        -Description "Allow QR Attendance Flask server on LAN only"
    Write-Host "[✓] تم إضافة قاعدة الفايروول: $ruleName (شبكة خاصة فقط)"
}
```

**الملفات:** إنشاء `c:\Projects\pwa\setup_firewall.ps1`

**التحقق:** شغّل السكربت كـ Administrator، ثم `Get-NetFirewallRule -DisplayName "QR-Attendance-Flask-5000"` — يجب أن يظهر `Enabled: True`.

---

### الخطوة 4: تحميل الموارد الخارجية محلياً (إزالة الاعتماد على CDN)

**ملفات تحتاج تنزيل:**
1. **SweetAlert2**: من `https://cdn.jsdelivr.net/npm/sweetalert2@11/dist/sweetalert2.all.min.js` → حفظ في `static/js/sweetalert2.all.min.js`
2. **qrcodejs**: من `https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js` → حفظ في `static/js/qrcode.min.js`
3. **Font Awesome 6.4.2 CSS**: ملف `static/css/font-awesome.min.css` موجود محلياً بالفعل — التحقق من كونه Font Awesome 6 أم 5؛ إذا كان إصدار قديم، نزّل CSS النص ووجّه الروابط له.

**تعديلات القوالب:**

**`base.html`:**
- استبدل: `<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>`
- بـ: `<script src="/static/js/sweetalert2.all.min.js"></script>`
- أبقِ رابط Google Fonts مع إضافة `font-display: swap` في CSS كـ fallback (Cairo محدد في `font-family: 'Cairo', -apple-system, ...` — سيعمل بخط النظام عند غياب الإنترنت)

**`student_scan.html`:**
- استبدل: `<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">`
- بـ: `<link rel="stylesheet" href="/static/css/font-awesome.min.css">`
- استبدل: `<link href="https://fonts.googleapis.com/...">`
- بـ: احذف (Cairo محدد كـ fallback في app.js/base — سيعمل بالخط الاحتياطي)

**`student_settings.html`:**
- استبدل Bootstrap RTL CDN بـ: `<link rel="stylesheet" href="/static/css/bootstrap.min.css">`
- استبدل Font Awesome CDN بـ: `<link rel="stylesheet" href="/static/css/font-awesome.min.css">`
- استبدل Google Fonts CDN بـ: احذف
- استبدل Bootstrap JS CDN بـ: `<script src="/static/js/bootstrap.bundle.min.js"></script>`

**`unified_login.html`:**
- استبدل Font Awesome CDN بـ: `<link rel="stylesheet" href="/static/css/font-awesome.min.css">`
- احذف Google Fonts CDN

**`network.html`:**
- استبدل: `<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js">`
- بـ: `<script src="/static/js/qrcode.min.js">`

**الملفات:** `base.html`، `student_scan.html`، `student_settings.html`، `unified_login.html`، `network.html`

**التحقق:** أوقف اتصال الإنترنت (أو افصل الكابل وأبقِ الراوتر يعمل)، شغّل الخادم، افتح `http://localhost:5000` في المتصفح — يجب أن تتحمل جميع الصفحات بالكامل مع أيقونات وتنسيق صحيح.

---

### الخطوة 5: إضافة SSE (Server-Sent Events) لمزامنة الحضور الفورية في واجهة الأستاذ

**القرار التصميمي:** استخدام SSE بدلاً من WebSocket — Flask يدعمه بشكل طبيعي بدون مكتبات إضافية، وهو أبسط للحالة الأحادية الاتجاه (الخادم → الأستاذ). يكفي لإشعار واجهة الأستاذ بكل تسجيل حضور جديد.

**ما يتغير في `app.py`:**

أ) إضافة آلية إشعار SSE — متغير عالمي يحتفظ بـ connected clients:
```python
import queue as _queue
_sse_clients = []  # list of (subject_id_or_None, Queue)
_sse_lock = threading.Lock()
```

ب) إضافة route جديد `/api/attendance-stream`:
```python
@app.route('/api/attendance-stream')
@login_required
def attendance_stream():
    """SSE stream: يُرسل حدث عند كل تسجيل حضور جديد"""
    subject_id = request.args.get('subject_id')
    q = _queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append((subject_id, q))
    
    def generate():
        try:
            yield f"data: connected\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {msg}\n\n"
                except _queue.Empty:
                    yield f": keepalive\n\n"
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove((subject_id, q))
                except ValueError:
                    pass
    
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
```

ج) إضافة دالة `_notify_attendance_update(subject_id, data)` تبثّ الحدث لجميع clients المشتركين في نفس المادة أو بدون فلتر:
```python
def _notify_attendance_update(subject_id, data):
    import json
    msg = json.dumps(data)
    with _sse_lock:
        dead = []
        for (client_subject, q) in _sse_clients:
            if client_subject is None or str(client_subject) == str(subject_id):
                try:
                    q.put_nowait(msg)
                except _queue.Full:
                    dead.append((client_subject, q))
        for item in dead:
            try:
                _sse_clients.remove(item)
            except ValueError:
                pass
```

د) في `student_api_scan_attendance()` و `api_scan_qr()`: بعد `record_attendance()` الناجح، أضف:
```python
_notify_attendance_update(subject_id, {
    'type': 'new_attendance',
    'subject_id': subject_id,
    'student_name': student.get('full_name', ''),
    'student_code': student.get('student_code', ''),
    'timestamp': datetime.now().isoformat()
})
```

**ما يتغير في `attendance.html`:**

أضف JavaScript في `{% block extra_js %}` لفتح SSE connection واستقبال الأحداث:
```javascript
let attendanceSSE = null;

function connectAttendanceSSE(subjectId) {
    if (attendanceSSE) attendanceSSE.close();
    if (!subjectId) return;
    
    attendanceSSE = new EventSource(`/api/attendance-stream?subject_id=${subjectId}`);
    
    attendanceSSE.onmessage = function(event) {
        if (event.data === 'connected' || event.data.startsWith(':')) return;
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'new_attendance') {
                // أعد تحميل جدول الحضور فقط إذا كانت المادة المعروضة هي نفسها
                const currentSubject = document.getElementById('subjectFilter').value;
                if (String(data.subject_id) === String(currentSubject)) {
                    loadAttendance(); // دالة موجودة بالفعل
                    // تحديث إحصائيات اليوم
                    loadTodayStats();
                }
            }
        } catch(e) {}
    };
    
    attendanceSSE.onerror = function() {
        // إعادة الاتصال التلقائية بعد 5 ثواني عند الانقطاع
        setTimeout(() => {
            const subjectId = document.getElementById('subjectFilter').value;
            if (subjectId) connectAttendanceSSE(subjectId);
        }, 5000);
    };
}

// ربط SSE بتغيير المادة المختارة
document.getElementById('subjectFilter').addEventListener('change', function() {
    connectAttendanceSSE(this.value);
});

// ربط SSE عند تحميل الصفحة إذا كانت مادة محددة
window.addEventListener('load', function() {
    const subjectId = document.getElementById('subjectFilter').value;
    if (subjectId) connectAttendanceSSE(subjectId);
});
```

**الملفات:** `app.py`، `templates/attendance.html`

**التحقق:** افتح صفحة الحضور واختر مادة — يجب أن يظهر "SSE متصل" في console. من جهاز آخر (أو نفس الجهاز في tab آخر)، سجّل حضوراً — يجب أن تتحدث القائمة فورياً دون refresh.

---

### الخطوة 6: معالجة HTTPS والكاميرا

**الوضع الحالي:** `student_scan.html` يفحص `isSecureContext` ويوفر بديلاً (التقاط صورة من الملف) — هذا يعمل على HTTP.

**الحل المختار: الإبقاء على HTTP مع تحسين تجربة المستخدم**

لا داعي لإعداد HTTPS معقد في البيئة المحلية. الكود موجود بالفعل لفتح كاميرا النظام عبر `<input type="file" capture="environment">` وهي تعمل على HTTP. المطلوب فقط:

1. في `student_scan.html` — تحسين رسالة الخطأ لتكون أوضح عند HTTP:
   - حالياً: `'الكاميرا المباشرة تحتاج HTTPS. استخدم خيار التقاط صورة QR.'`
   - المحسّنة: `'الكاميرا المباشرة تحتاج HTTPS. اضغط زر "التقاط صورة QR" أدناه — يعمل بشكل طبيعي على هاتفك!'`

2. في `student_scan.html` — عند `!isSecureContext`، أخفِ زر "افتح الكاميرا" وأظهر زر "التقاط صورة QR" بشكل بارز وتلقائياً:
   ```javascript
   // في بداية startScan()
   if (!window.isSecureContext) {
       document.getElementById('qrImageInput').click(); // فتح كاميرا النظام مباشرة
       return;
   }
   ```

**ملاحظة في التوثيق:** إذا أراد المستخدم الكاميرا المباشرة (live camera) — يحتاج إعداد HTTPS محلي (self-signed certificate + ثقة على الهاتف). هذا إجراء يدوي خارج نطاق هذه الخطة.

**الملفات:** `student_scan.html`

**التحقق:** افتح الموقع من هاتف على الشبكة المحلية عبر HTTP — زر "التقاط صورة QR" يجب أن يفتح كاميرا الهاتف مباشرة.

---

### الخطوة 7: تحديث `RUN_SERVER.bat` وإضافة توجيهات الإعداد

**ما يتغير في `RUN_SERVER.bat`:**
- أضف عرض عنوان IP الشبكة تلقائياً عند التشغيل:
  ```batch
  FOR /f "tokens=2 delims=:" %%i IN ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') DO (
      SET LAN_IP=%%i
      goto :found_ip
  )
  :found_ip
  SET LAN_IP=%LAN_IP: =%
  echo [i] رابط الطلاب على الشبكة: http://%LAN_IP%:5000
  ```
- أضف تحقق من قواعد الفايروول وعرض تحذير إذا لم تكن موجودة.

**الملفات:** `RUN_SERVER.bat`

**التحقق:** شغّل `RUN_SERVER.bat` — يجب أن يعرض رابط LAN الصحيح تلقائياً.

---

### الخطوة 8: تحسين صفحة الشبكة `/network` للعمل بدون hotspot.ps1

**الوضع الحالي:** الصفحة تدعم وضعين: Hotspot Windows (192.168.137.1) أو الشبكة الحالية.

**ما يتغير في `app.py` — دالة `api_network_info()`:**
- أضف كشف IP الشبكة المحلية الحقيقي (شبكة الراوتر):
  ```python
  # اكتشاف IP على شبكة الراوتر
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.connect(('8.8.8.8', 80))
  local_ip = s.getsockname()[0]
  s.close()
  ```
  هذا يعطي IP الواجهة المتصلة بالراوتر دون إرسال أي بيانات فعلياً.

- أضف في الاستجابة: `'router_ip': local_ip` و `'student_url': f'http://{local_ip}:{server_port}'`

**ما يتغير في `network.html`:**
- أضف عرض رابط الراوتر بجانب رابط الهوتسبوت:
  ```javascript
  // عرض رابط الراوتر دائماً كخيار بديل
  if (data.router_ip) {
      document.getElementById('routerUrl').textContent = `http://${data.router_ip}:${serverPort}`;
  }
  ```
- أضف عنصر HTML لعرض رابط الراوتر مع زر نسخ وـ QR code.

**الملفات:** `app.py`، `templates/network.html`

**التحقق:** افتح `/network` — يجب أن يظهر رابط الشبكة المحلية الصحيح، وعند فتحه من هاتف متصل بنفس الراوتر، يفتح الموقع.

---

## ملخص الملفات المُعدَّلة والمُنشأة

| الملف | نوع التغيير | المرحلة |
|-------|------------|---------|
| `database.py` | تعديل: WAL mode + UNIQUE index على attendance | 1 |
| `setup_firewall.ps1` | إنشاء جديد | 3 |
| `static/js/sweetalert2.all.min.js` | إنشاء (تنزيل من CDN) | 4 |
| `static/js/qrcode.min.js` | إنشاء (تنزيل من CDN) | 4 |
| `templates/base.html` | تعديل: استبدال SweetAlert2 CDN بالمحلي | 4 |
| `templates/student_scan.html` | تعديل: استبدال CDN بالمحلية + تحسين تجربة HTTP | 4، 6 |
| `templates/student_settings.html` | تعديل: استبدال كل CDN بالمحلية | 4 |
| `templates/unified_login.html` | تعديل: استبدال CDN بالمحلية | 4 |
| `templates/network.html` | تعديل: qrcodejs محلي + عرض router IP | 4، 8 |
| `app.py` | تعديل: إضافة SSE endpoint + notify function + router IP | 5، 8 |
| `templates/attendance.html` | تعديل: إضافة SSE client JavaScript | 5 |
| `RUN_SERVER.bat` | تعديل: عرض LAN IP تلقائياً | 7 |

---

## قرارات تصميمية مع مبرراتها

1. **WAL mode كـ middleware في `get_db_connection()` لا في `init_database()`**: WAL يجب تفعيله في كل اتصال، لأن إعداد `journal_mode` لا يستمر تلقائياً عبر الاتصالات في بعض الأنظمة.

2. **UNIQUE INDEX لا UNIQUE constraint في تعريف الجدول**: البيانات موجودة، وتغيير تعريف الجدول يتطلب إعادة بناء الجدول. `CREATE UNIQUE INDEX IF NOT EXISTS` أسلم وأسرع.

3. **SSE لا WebSocket**: Flask لا يدعم WebSocket بشكل طبيعي (يحتاج `flask-socketio` + Eventlet/Gevent). SSE يعمل مع Flask الاعتيادي ويكفي لحالتنا (الخادم → الأستاذ فقط). هذا يتجنب تغيير نظام التشغيل.

4. **HTTP مع input[capture] لا HTTPS**: إعداد HTTPS محلي موثوق (valid على الهاتف) يتطلب إنشاء CA خاصة وتثبيتها على كل هاتف — عملية معقدة لبيئة تعليمية. البديل الموجود (`input[type=file][capture=environment]`) يعمل على HTTP ويفتح كاميرا الهاتف مباشرة.

5. **الحفاظ على lan_sync.py دون تعديل**: البلوبريprint موجود ويعمل كمزامنة مع السحابة. التغييرات الجديدة (SSE) لا تتعارض معه.

---

## إجراءات يدوية للمستخدم (لا يمكن أتمتتها)

1. **معرفة IP الحاسوب**: `ipconfig` في cmd أو PowerShell — قسم Wi-Fi أو Ethernet.
2. **تشغيل `setup_firewall.ps1` كـ Administrator**: `Right-click → Run with PowerShell as Admin`.
3. **DHCP Reservation (اختياري)**: في إعدادات الراوتر، احجز IP ثابت لـ MAC address الحاسوب — يمنع تغيير IP عند إعادة التشغيل.
4. **Client Isolation على الراوتر**: إذا كان الطلاب لا يستطيعون الوصول للخادم رغم الاتصال بالشبكة نفسها، افحص إعداد "AP Isolation" أو "Client Isolation" في الراوتر وأوقفه.
