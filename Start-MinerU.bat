@echo off
rem ===========================================================================
rem  MinerU 4.0.10 - Portable one-click launcher
rem
rem  This file is intentionally PURE ASCII.  cmd.exe parses .bat files using the
rem  OEM code page (936 / GBK on zh-CN Windows); UTF-8 multi-byte sequences can
rem  swallow the trailing CRLF and glue the next line into a comment, which shows
rem  up as bogus errors like "'m' is not recognized as an internal command".
rem  All Chinese UI text is printed by app\launcher.py instead.
rem
rem  Usage:
rem    - double click                       -> interactive menu
rem    - drag & drop files onto this file   -> parse them directly
rem ===========================================================================

chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"
title MinerU 4.0.10 Portable

rem --- keep the bundled interpreter insulated from the host machine ---
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH="
set "PYTHONHOME="
rem --- no console window flash for helper processes ---
set "PYTHONLEGACYWINDOWSSTDIO=0"

rem --- step 0: the portable Python runtime itself (needs PowerShell, no Python yet) ---
rem     NOTE: inside a parenthesised block an unquoted ")" in echo text closes the
rem     block early and cmd then reports ". was unexpected at this time."
rem     Keep every echo line inside the blocks below free of parentheses.
if not exist "%~dp0runtime\python\python.exe" (
  echo.
  echo   [setup] Bundled Python runtime not found. Downloading it now
  echo           about 47 MB, progress printed in English by PowerShell
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_python.ps1"
  if not exist "%~dp0runtime\python\python.exe" (
    echo.
    echo   [ERROR] Could not prepare the bundled Python runtime.
    echo.
    echo   If this machine has no internet access, use the FULL offline
    echo   package instead of this slim one -- see README.
    echo.
    pause
    endlocal
    exit /b 1
  )
)

rem --- step 1/2: Python deps and model weights are checked and downloaded
rem         automatically by app\launcher.py on first run ---
"%~dp0runtime\python\python.exe" "%~dp0app\launcher.py" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
  echo.
  echo   MinerU exited with code %CODE%
  echo.
  pause
)
endlocal
exit /b %CODE%
