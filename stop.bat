@echo off
title Stop Seller Desk
setlocal enabledelayedexpansion
set "FOUND="

rem Find whatever is listening on port 8000 and stop it only if it is Python (the Seller Desk server)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (
  if not "%%P"=="0" (
    tasklist /FI "PID eq %%P" /NH 2>nul | find /i "python" >nul && (
      taskkill /PID %%P /T /F >nul 2>&1 && (
        echo Stopped Seller Desk ^(process %%P^).
        set "FOUND=1"
      )
    )
  )
)

if not defined FOUND (
  echo Seller Desk is not running.
)
echo.
timeout /t 3 >nul
