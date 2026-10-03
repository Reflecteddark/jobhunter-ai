@echo off
chcp 65001 >nul
title RevOps Enterprise OS - Onboarding Wizard
color 0B

cd /d "C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai\multitenant_revops"

where python >nul 2>&1
if %errorlevel% equ 0 (
    python onboard_client_wizard.py
) else (
    "C:\Python314\python.exe" onboard_client_wizard.py
)

if %errorlevel% neq 0 (
    echo.
    echo [!] Process exited with code %errorlevel%.
    pause
)
