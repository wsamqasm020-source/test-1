@echo off
:: شغّل هذا الملف كمسؤول (Run as Administrator) لفتح منفذ HTTPS
echo Adding firewall rule for Attendance HTTPS (port 5443)...
netsh advfirewall firewall add rule name="Attendance HTTPS LAN" dir=in action=allow protocol=TCP localport=5443 profile=private
if %ERRORLEVEL% EQU 0 (
    echo [OK] Firewall rule added successfully.
) else (
    echo [ERROR] Failed. Make sure you ran this as Administrator.
)
pause
