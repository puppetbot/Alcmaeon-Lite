@echo off
rem Builds a single Alcmaeon Lite.exe that runs with no Python installed.
rem Takes a few minutes. The result appears in the dist folder.
cd /d "%~dp0"
where py >nul 2>&1 && ( py -3 "bootstrap.py" --build & pause & exit /b )
where python >nul 2>&1 && ( python "bootstrap.py" --build & pause & exit /b )
echo Python is required to build. Install it from https://www.python.org/downloads/
pause
