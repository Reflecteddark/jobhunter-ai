@echo off
title JobHunter AI - Stopper
chcp 65001 >nul

echo ===================================================
echo Остановка JobHunter AI и n8n...
echo ===================================================

echo [1/3] Завершение задачи в планировщике...
schtasks /End /TN "JobHunter_N8N" >nul 2>&1

echo [2/3] Освобождение порта 5678...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5678" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)
taskkill /F /IM node.exe >nul 2>&1

echo [3/3] Остановка демона синхронизации HH...
wmic process where "commandline like '%%hh_status_sync_daemon.py%%'" call terminate >nul 2>&1

echo.
echo ===================================================
netstat -ano | findstr ":5678" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [OK] Порт 5678 свободен, n8n остановлен.
) else (
    echo [!] Порт 5678 еще занят.
)
echo ===================================================
timeout /t 3 /nobreak >nul
exit
