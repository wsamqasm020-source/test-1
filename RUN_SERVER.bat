@echo off
chcp 65001 >nul
cls
cd /d "%~dp0"
echo ====================================
echo   نظام الحضور - تشغيل السيرفر
echo ====================================
echo.

REM تفعيل بيئة مساحة العمل أولاً
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

REM التحقق من تثبيت المكتبات
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [!] Flask غير مثبت، جاري التثبيت...
    pip install -r requirements.txt
)

echo.
echo [✓] جاري تشغيل السيرفر...
echo [i] رابط المدرس (هذا الجهاز): http://127.0.0.1:5000

REM اكتشاف IP الشبكة المحلية
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "192.168" ') do set LAN_IP=%%a
if defined LAN_IP (
    set LAN_IP=%LAN_IP: =%
    echo [i] رابط الطلاب على الشبكة: http://%LAN_IP%:5000
) else (
    echo [i] رابط الطلاب على الشبكة: http://192.168.0.190:5000  (تحقق من ipconfig)
)
echo [i] للإيقاف: اضغط Ctrl+C
echo.
echo ====================================
echo.

REM تشغيل السيرفر
python app.py

pause
