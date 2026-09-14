@echo off
chcp 65001 > nul
echo Đang tắt tiến trình bot...
taskkill /F /FI "COMMANDLINE eq *d:\tool\img\main.py*" /T > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Đã tắt bot thành công!
) else (
    taskkill /F /IM python.exe /T > nul 2>&1
    echo [OK] Đã tắt các tiến trình Python.
)
pause

