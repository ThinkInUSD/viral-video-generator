@echo off
title ViralForge Setup
color 0A
echo.
echo  ============================================
echo   ViralForge - Installing dependencies...
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo  ERROR: Python not found. Install Python 3.10+ from python.org
  pause
  exit /b 1
)

echo  Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  ERROR: pip install failed. Try running as Administrator.
  pause
  exit /b 1
)

echo.
echo  ============================================
echo   Done! Next steps:
echo   1. Install Ollama from ollama.com
echo   2. Run in a terminal: ollama pull llama3.2
echo   3. Double-click start.bat to launch
echo  ============================================
echo.
pause
