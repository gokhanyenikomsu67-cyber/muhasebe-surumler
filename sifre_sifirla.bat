@echo off
chcp 65001 >nul
title Muhasebe - Sifre Sifirlama
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Program henuz kurulmamis. Once baslat.bat dosyasina cift tiklayin.
  pause
  exit /b
)
".venv\Scripts\python.exe" sifre_sifirla.py
echo.
pause
