@echo off
setlocal

cd /d "%~dp0.."

start "WorkMemory Backend" cmd /k "%~dp0dev_start_backend.bat"
start "WorkMemory Desktop" cmd /k "%~dp0dev_start_desktop.bat"
