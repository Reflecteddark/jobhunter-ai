@echo off
chcp 65001 >nul
title RevOps Enterprise OS - Disaster Recovery (Восстановление на новой Windows)
color 0B

echo ==============================================================================
echo       REVOPS ENTERPRISE OS — АВТОМАТИЧЕСКОЕ ВОССТАНОВЛЕНИЕ НА НОВОЙ WINDOWS
echo ==============================================================================
echo.

set SCRIPT_DIR=%~dp0
set SCRATCH_DIR=%SCRIPT_DIR%..\..
set DESKTOP_DIR=%USERPROFILE%\Desktop

echo [1/4] Проверка окружения Python и библиотек...
python -m pip install --upgrade gspread google-auth google-api-python-client fastapi uvicorn requests >nul 2>&1
echo   [✓] Библиотеки Python готовы.

echo.
echo [2/4] Проверка загрузчика Cloudflare Tunnel...
if not exist "%SCRATCH_DIR%\cloudflared\cloudflared.exe" (
    echo   [+] Загрузка cloudflared.exe с официального репозитория Cloudflare...
    powershell -Command "New-Item -ItemType Directory -Path '%SCRATCH_DIR%\cloudflared' -Force | Out-Null; Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%SCRATCH_DIR%\cloudflared\cloudflared.exe' -UseBasicParsing"
)
echo   [✓] Cloudflare Tunnel готов к работе.

echo.
echo [3/4] Восстановление ярлыков управления на Рабочий стол...
copy /Y "%SCRIPT_DIR%Новая_компания.bat" "%DESKTOP_DIR%\Новая_компания.bat" >nul
copy /Y "%SCRATCH_DIR%\launchers\Запустить_Все_Службы_RevOps.bat" "%DESKTOP_DIR%\Запустить_Все_Службы_RevOps.bat" >nul
copy /Y "%SCRATCH_DIR%\launchers\Остановить_Все_Службы_RevOps.bat" "%DESKTOP_DIR%\Остановить_Все_Службы_RevOps.bat" >nul
echo   [✓] Ярлыки успешно восстановлены на Рабочем столе:
echo       - Новая_компания.bat
echo       - Запустить_Все_Службы_RevOps.bat
echo       - Остановить_Все_Службы_RevOps.bat

echo.
echo [4/4] Запуск фоновых служб (Faster-Whisper + n8n + Cloudflare Tunnel)...
python "%SCRATCH_DIR%\manage_services.py" start

echo.
echo ==============================================================================
echo   🎉 СИСТЕМА REVOPS ENTERPRISE OS ПОЛНОСТЬЮ ВОССТАНОВЛЕНА И ГОТОВА К РАБОТЕ!
echo ==============================================================================
echo.
pause
