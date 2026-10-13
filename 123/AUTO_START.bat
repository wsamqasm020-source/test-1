@echo off
cd /d "C:\Users\user\OneDrive\Desktop\pwa\تعديلات قاسم"
call venv\Scripts\activate.bat
start /min python app.py
echo [✓] السيرفر شغال على http://127.0.0.1:5000
