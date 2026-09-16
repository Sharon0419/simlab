@echo off
cd /d "%~dp0"
if exist "dist\SimLab-v0.12.0\SimLab.exe" (
    start "" "%~dp0dist\SimLab-v0.12.0\SimLab.exe"
    exit /b
)
if exist "dist\SimLab-v0.11.0\SimLab.exe" (
    start "" "%~dp0dist\SimLab-v0.11.0\SimLab.exe"
    exit /b
)
if exist "dist\SimLab-v0.10.1\SimLab.exe" (
    start "" "%~dp0dist\SimLab-v0.10.1\SimLab.exe"
    exit /b
)
if exist "dist\SimLab-v0.10.0\SimLab.exe" (
    start "" "%~dp0dist\SimLab-v0.10.0\SimLab.exe"
    exit /b
)
if exist "dist\SimLab\SimLab.exe" (
    start "" "%~dp0dist\SimLab\SimLab.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b
)
echo Please create .venv and install requirements.txt first.
pause
