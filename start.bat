@echo off
cd /d "%~dp0"
echo ==========================================
echo    نظام تسجيل الحضور بالـ QR + Face Recognition
echo ==========================================
echo.
echo جاري تشغيل التطبيق...
echo.

REM استخدام Python الرئيسي (حيث OpenCV مثبت)
python app.py

echo.
pause
