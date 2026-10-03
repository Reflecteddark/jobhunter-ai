@echo off
title JobHunter AI - Starter

set "NODE_OPTIONS=--dns-result-order=ipv4first --max-old-space-size=4096"

echo ===================================================
echo [1/3] Check and start n8n...
echo ===================================================

set "N8N_STATUS=000"
for /f "tokens=*" %%a in ('curl -s -m 2 -o nul -w "%%{http_code}" http://localhost:5678/healthz 2^>nul') do set "N8N_STATUS=%%a"

if "%N8N_STATUS%"=="200" (
    echo n8n is already running on port 5678.
    goto sync_hh
)

echo Starting n8n service...
schtasks /Run /TN "JobHunter_N8N" >nul 2>&1
start "" "C:\Python314\pythonw.exe" "C:\Users\strel\.gemini\antigravity\scratch\run_n8n_silent.py" >nul 2>&1

echo Waiting for n8n to initialize...
set attempts=0

:wait_n8n
ping -n 3 127.0.0.1 >nul
set "N8N_STATUS=000"
for /f "tokens=*" %%a in ('curl -s -m 2 -o nul -w "%%{http_code}" http://localhost:5678/healthz 2^>nul') do set "N8N_STATUS=%%a"

if "%N8N_STATUS%"=="200" (
    echo n8n is up on port 5678!
    goto sync_hh
)

set /a attempts+=1
if %attempts% geq 12 (
    echo [!] n8n is starting slower than usual, opening browser...
    goto sync_hh
)
goto wait_n8n

:sync_hh
echo.
echo ===================================================
echo [2/3] Auto-sync HH response statuses...
echo ===================================================
if exist "C:\Users\strel\.gemini\antigravity\scratch\hh_status_sync_daemon.py" (
    start "" /b "C:\Python314\pythonw.exe" "C:\Users\strel\.gemini\antigravity\scratch\hh_status_sync_daemon.py" >nul 2>&1
    echo Sync daemon launched in background.
)

:open_browser
echo.
echo ===================================================
echo [3/3] Opening UI...
echo ===================================================
if /i not "%1"=="--silent" (
    start http://localhost:5678
)

echo.
echo ===================================================
echo  Services are active.
echo  Window closes in 3 seconds.
echo ===================================================
ping -n 4 127.0.0.1 >nul
exit
