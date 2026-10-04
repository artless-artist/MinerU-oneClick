@echo off
rem Portable shim for the MinerU `mineru-webui` command (pure ASCII on purpose).
rem Calls the bundled interpreter + app\cli.py so the package stays relocatable
rem (pip-generated Scripts\*.exe embed an absolute python path and break when moved).
setlocal
set "ROOT=%~dp0..\.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH="
set "PYTHONHOME="
"%ROOT%\runtime\python\python.exe" "%ROOT%\app\cli.py" mineru-webui %*
exit /b %ERRORLEVEL%
