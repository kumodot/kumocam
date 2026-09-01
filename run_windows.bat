@echo off
REM KumoCam launcher (Windows)
REM Creates a local virtual environment on first run and keeps its
REM dependencies in sync with requirements.txt on every launch.
cd /d "%~dp0"
if not exist .venv (
    echo First run: creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Checking dependencies...
pip install -q -r requirements.txt
python -m kumocam.main
pause
