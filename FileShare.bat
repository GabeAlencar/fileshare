@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw fileshare.py) || (start "" pythonw fileshare.py)
