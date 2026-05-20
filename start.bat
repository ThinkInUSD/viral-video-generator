@echo off
title ViralForge Pro
color 0B
echo.
echo  ============================================
echo   ViralForge Pro - Viral Content Engine
echo  ============================================
echo.
echo  Using Groq API (free) by default.
echo  Set GROQ_API_KEY in the app Settings panel.
echo.
echo  To use Ollama instead, make sure it is
echo  running in another terminal: ollama serve
echo.
timeout /t 2 /nobreak >nul
start "" "http://localhost:8080"
cd /d "%~dp0"
python app.py
echo.
pause
