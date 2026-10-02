@echo off
title JobHunter AI - Starter
chcp 65001 >nul

set "NODE_OPTIONS=--dns-result-order=ipv4first --max-old-space-size=4096"

echo ===================================================
echo [1/3] Проверка и запуск n8n...
echo ===================================================
netstat -ano | findstr /I "LISTENING" | findstr /C:":5678 " >nul
if not errorlevel 1 (
    echo n8n уже работает на порту 5678.
    goto sync_hh
)

echo Запуск n8n через задачу Windows...
schtasks /Run /TN "JobHunter_N8N" >nul 2>&1

echo Ожидание инициализации n8n...
set attempts=0

:wait_n8n
timeout /t 2 /nobreak >nul
netstat -ano | findstr /I "LISTENING" | findstr /C:":5678 " >nul
if not errorlevel 1 (
    echo n8n успешно поднят на порту 5678!
    goto sync_hh
)

set /a attempts+=1
if %attempts% geq 10 (
    echo [!] n8n запускается медленнее обычного...
    goto sync_hh
)
goto wait_n8n

:sync_hh
echo.
echo ===================================================
echo [2/3] Автосинхронизация откликов HH...
echo ===================================================
if exist "C:\Users\strel\.gemini\antigravity\scratch\hh_status_sync_daemon.py" (
    start "" /b python "C:\Users\strel\.gemini\antigravity\scratch\hh_status_sync_daemon.py" >nul 2>&1
    echo Демон синхронизации HH запущен в фоне.
)

:open_browser
echo.
echo ===================================================
echo [3/3] Открытие интерфейса...
echo ===================================================
if /i not "%1"=="--silent" (
    start http://localhost:5678
)

echo.
echo ===================================================
echo  Сервисы активны.
echo ===================================================
timeout /t 3 /nobreak >nul
exit
