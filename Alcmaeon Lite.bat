@echo off
rem ===================================================================
rem  Alcmaeon Lite -- Windows launcher
rem  Double-click this file. First run installs what it needs (a few
rem  minutes); after that it opens straight away.
rem ===================================================================
cd /d "%~dp0"

rem pyw / pythonw run without a console window flashing up.
where pyw >nul 2>&1 && (
    start "" pyw -3 "bootstrap.py" %*
    exit /b
)
where pythonw >nul 2>&1 && (
    start "" pythonw "bootstrap.py" %*
    exit /b
)
where py >nul 2>&1 && (
    py -3 "bootstrap.py" %*
    exit /b
)
where python >nul 2>&1 && (
    python "bootstrap.py" %*
    exit /b
)

echo.
echo   Python is not installed on this PC.
echo.
echo   Install it from  https://www.python.org/downloads/
echo   IMPORTANT: tick "Add python.exe to PATH" in the installer.
echo.
echo   Then double-click this file again.
echo.
pause
