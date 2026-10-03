@echo off
title JobHunter AI - Stopper

echo ===================================================
echo Stopping JobHunter AI and n8n...
echo ===================================================

echo [1/3] Ending scheduled task...
schtasks /End /TN "JobHunter_N8N" >nul 2>&1

echo [2/3] Freeing port 5678...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5678" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)
taskkill /F /IM node.exe >nul 2>&1

echo [3/3] Stopping HH sync daemon...
wmic process where "commandline like '%%hh_status_sync_daemon.py%%'" call terminate >nul 2>&1

echo.
echo ===================================================
netstat -ano | findstr ":5678" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [OK] Port 5678 is free, n8n stopped.
) else (
    echo [!] Port 5678 is still busy.
)
echo ===================================================
ping -n 4 127.0.0.1 >nul
exit
