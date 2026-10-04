@echo off
chcp 65001 >nul
title RevOps Enterprise OS - CRM and n8n Integration Manager
color 0A

cd /d "C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai\multitenant_revops"

where python >nul 2>&1
if %errorlevel% equ 0 (
    python crm_integration_manager.py
) else (
    "C:\Python314\python.exe" crm_integration_manager.py
)

if %errorlevel% neq 0 (
    echo.
    echo [!] Process exited with code %errorlevel%.
    pause
)
