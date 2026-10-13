@echo off
chcp 65001 >nul
cls
cd /d "%~dp0"
echo ==========================================
echo    نظام تسجيل الحضور - شبكة LAN
echo ==========================================
echo.
echo [جاري البحث عن عنوان IP المحلي...]
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "192.168" ') do set LOCAL_IP=%%a
if defined LOCAL_IP (
    set LOCAL_IP=%LOCAL_IP: =%
    echo [+] عنوان الشبكة المحلية: %LOCAL_IP%
    echo.
    echo [HTTP]  رابط الطلاب (بدون كاميرا مباشرة):
    echo         http://%LOCAL_IP%:5000
    echo.
    echo [HTTPS] رابط الطلاب (مع كاميرا - يحتاج تثبيت الشهادة):
    echo         https://%LOCAL_IP%:5443
    echo.
    echo [i] للكاميرا المباشرة استخدم HTTPS (5443) - راجع INSTALL_CERT.md
    echo [i] للوصول بدون شهادة استخدم HTTP (5000) مع زر "التقاط صورة QR"
) else (
    echo [!] تحقق من اتصالك بالشبكة المحلية
    echo [i] HTTP  افتراضي: http://192.168.0.190:5000
    echo [i] HTTPS افتراضي: https://192.168.0.190:5443
)
echo.
echo ==========================================
echo.

REM تفعيل البيئة الافتراضية
if exist "%~dp0..\.venv\Scripts\activate.bat" (
    echo [✓] تفعيل بيئة مساحة العمل .venv...
    call "%~dp0..\.venv\Scripts\activate.bat"
) else (
    if exist "%~dp0.venv\Scripts\activate.bat" (
        call "%~dp0.venv\Scripts\activate.bat"
    ) else (
        if exist "%~dp0venv\Scripts\activate.bat" (
            echo [✓] تفعيل البيئة الافتراضية...
            call "%~dp0venv\Scripts\activate.bat"
        ) else (
            echo [!] تحذير: البيئة الافتراضية غير موجودة
            echo.
        )
    )
)

echo [+] جاري تشغيل الخادم على جميع الواجهات...
echo [i] HTTP  port 5000 - للوصول العادي
echo [i] HTTPS port 5443 - للكاميرا (يحتاج cert.pem/key.pem)
echo [i] للإيقاف: اضغط Ctrl+C
echo.
python app.py
pause
