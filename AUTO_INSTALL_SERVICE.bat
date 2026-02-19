@echo off
REM ============================================================
REM Auto-Install StudioPingService - Complete Setup
REM Run as Administrator
REM ============================================================

setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo    Studio Ping Service - Auto Installer
echo ============================================================
echo.

REM Check if running as Administrator
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERROR] This script MUST be run as Administrator!
    echo.
    echo Right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo [OK] Running as Administrator
echo.

REM ============================================================
REM Get Script Path (where client_ping.py is located)
REM ============================================================

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
set CLIENT_SCRIPT=%SCRIPT_DIR%\client_ping.py

echo Script Directory: %SCRIPT_DIR%
echo Client Script: %CLIENT_SCRIPT%
echo.

REM Check if client_ping.py exists
if not exist "%CLIENT_SCRIPT%" (
    echo [ERROR] client_ping.py not found at: %CLIENT_SCRIPT%
    echo.
    echo Please ensure this bat file is in the same folder as client_ping.py
    echo.
    pause
    exit /b 1
)

echo [OK] Found client_ping.py
echo.

REM ============================================================
REM Check NSSM
REM ============================================================

set NSSM_PATH=C:\nssm\win64\nssm.exe

if not exist "%NSSM_PATH%" (
    echo [ERROR] NSSM not found at: %NSSM_PATH%
    echo.
    echo Please install NSSM first:
    echo 1. Download from: https://nssm.cc/download
    echo 2. Extract to C:\nssm\
    echo.
    pause
    exit /b 1
)

echo [OK] Found NSSM
echo.

REM ============================================================
REM Check and Install Python
REM ============================================================

echo Checking Python installation...
set PYTHON_EXE=
set PYTHON_FOUND=0

REM Try to find Python
where python >nul 2>&1
if %errorLevel% EQU 0 (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        set PYTHON_EXE=%%i
        set PYTHON_FOUND=1
        goto :python_found
    )
)

:python_found
if %PYTHON_FOUND% EQU 1 (
    echo [OK] Found Python: %PYTHON_EXE%
    for /f "delims=" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do echo     Version: %%v
    echo.
) else (
    echo [WARNING] Python not found in PATH
    echo.
    echo Attempting to install Python using winget...
    echo.
    
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    
    if %errorLevel% NEQ 0 (
        echo [ERROR] Failed to auto-install Python
        echo.
        echo Please install Python manually:
        echo 1. Download from: https://www.python.org/downloads/
        echo 2. Run installer and CHECK "Add Python to PATH"
        echo 3. Run this script again
        echo.
        pause
        exit /b 1
    )
    
    echo [OK] Python installed successfully
    echo Refreshing PATH...
    
    REM Refresh environment variables
    for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%b"
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%b"
    set "PATH=%SYS_PATH%;%USR_PATH%"
    
    REM Try finding Python again
    where python >nul 2>&1
    if %errorLevel% EQU 0 (
        for /f "delims=" %%i in ('where python 2^>nul') do set PYTHON_EXE=%%i
        echo [OK] Python found after installation: !PYTHON_EXE!
    ) else (
        echo [ERROR] Python installed but not found in PATH
        echo Please restart this script or reboot your computer
        pause
        exit /b 1
    )
)

echo.

REM ============================================================
REM Install Python Dependencies
REM ============================================================

echo Installing Python dependencies...
"%PYTHON_EXE%" -m pip install --upgrade pip --quiet
"%PYTHON_EXE%" -m pip install requests --quiet

if %errorLevel% NEQ 0 (
    echo [WARNING] Failed to install some packages, trying again...
    "%PYTHON_EXE%" -m pip install requests
)

echo [OK] Python dependencies installed
echo.

REM ============================================================
REM Read Environment Variables from User Registry
REM ============================================================

echo Reading environment variables...

set USER_OBS_SERVERS=
set USER_AGENT_NAME=
set USER_SERVER_URL=

for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v OBS_STREAMING_SERVERS 2^>nul ^| find "OBS_STREAMING_SERVERS"') do set USER_OBS_SERVERS=%%b
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v AGENT_NAME 2^>nul ^| find "AGENT_NAME"') do set USER_AGENT_NAME=%%b
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v SERVER_URL 2^>nul ^| find "SERVER_URL"') do set USER_SERVER_URL=%%b

if not "!USER_OBS_SERVERS!"=="" (
    echo [OK] OBS_STREAMING_SERVERS: !USER_OBS_SERVERS!
) else (
    echo [INFO] OBS_STREAMING_SERVERS not set - will use defaults or server targets
)

if not "!USER_AGENT_NAME!"=="" (
    echo [OK] AGENT_NAME: !USER_AGENT_NAME!
) else (
    echo [INFO] AGENT_NAME not set - will use computer name
)

if not "!USER_SERVER_URL!"=="" (
    echo [OK] SERVER_URL: !USER_SERVER_URL!
) else (
    echo [INFO] SERVER_URL not set - will use default
)

echo.

REM ============================================================
REM Remove Existing Service (if exists)
REM ============================================================

set SERVICE_NAME=StudioPingService

echo Checking for existing service...
sc query %SERVICE_NAME% >nul 2>&1

if %errorLevel% EQU 0 (
    echo [FOUND] Existing service found - removing...
    
    echo Stopping service...
    "%NSSM_PATH%" stop %SERVICE_NAME% >nul 2>&1
    timeout /t 3 /nobreak >nul
    
    echo Removing service...
    "%NSSM_PATH%" remove %SERVICE_NAME% confirm >nul 2>&1
    timeout /t 2 /nobreak >nul
    
    echo [OK] Old service removed
) else (
    echo [INFO] No existing service found
)

echo.

REM ============================================================
REM Install New Service
REM ============================================================

echo Installing service...
"%NSSM_PATH%" install %SERVICE_NAME% "%PYTHON_EXE%" "%CLIENT_SCRIPT%"

if %errorLevel% NEQ 0 (
    echo [ERROR] Failed to install service!
    pause
    exit /b 1
)

echo [OK] Service installed
echo.

REM ============================================================
REM Configure Service
REM ============================================================

echo Configuring service...

"%NSSM_PATH%" set %SERVICE_NAME% AppDirectory "%SCRIPT_DIR%"
"%NSSM_PATH%" set %SERVICE_NAME% DisplayName "Studio Ping Monitor Service"
"%NSSM_PATH%" set %SERVICE_NAME% Description "Monitors network latency to streaming servers - Auto-detects OBS servers from registry"
"%NSSM_PATH%" set %SERVICE_NAME% Start SERVICE_AUTO_START

REM NOTE: Service automatically reads OBS_STREAMING_SERVERS from user registry
REM No need to set environment variables - the Python code scans all logged-in users
REM This ensures real-time detection when OBS plugin updates the registry
echo [INFO] Service will auto-detect servers from OBS plugin registry settings
echo [INFO] No manual configuration needed - runs as LocalSystem with user registry access

REM Configure logging
set LOG_DIR=%SCRIPT_DIR%\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

"%NSSM_PATH%" set %SERVICE_NAME% AppStdout "%LOG_DIR%\service_stdout.log"
"%NSSM_PATH%" set %SERVICE_NAME% AppStderr "%LOG_DIR%\service_stderr.log"
"%NSSM_PATH%" set %SERVICE_NAME% AppStdoutCreationDisposition 4
"%NSSM_PATH%" set %SERVICE_NAME% AppStderrCreationDisposition 4
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateOnline 1
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateSeconds 86400
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateBytes 10485760

REM Auto-restart on failure
"%NSSM_PATH%" set %SERVICE_NAME% AppExit Default Restart
"%NSSM_PATH%" set %SERVICE_NAME% AppRestartDelay 5000

echo [OK] Service configured
echo.

REM ============================================================
REM Start Service
REM ============================================================

echo Starting service...
"%NSSM_PATH%" start %SERVICE_NAME%

if %errorLevel% NEQ 0 (
    echo [WARNING] Service start returned error code
    echo Waiting to check status...
) else (
    echo [OK] Service start command sent
)

echo.
echo Waiting 5 seconds for service to initialize...
timeout /t 5 /nobreak >nul

REM ============================================================
REM Verify Service Status
REM ============================================================

echo.
echo ============================================================
echo    Verification
echo ============================================================
echo.

sc query %SERVICE_NAME% | find "STATE"

echo.
echo Checking logs...
timeout /t 2 /nobreak >nul

if exist "%LOG_DIR%\service_stdout.log" (
    echo.
    echo --- Last 15 lines of log ---
    powershell -Command "Get-Content '%LOG_DIR%\service_stdout.log' -Tail 15 -ErrorAction SilentlyContinue"
) else (
    echo [INFO] Log file not created yet
)

echo.
echo ============================================================
echo    Installation Complete!
echo ============================================================
echo.
echo Service Name: %SERVICE_NAME%
echo Python: %PYTHON_EXE%
echo Script: %CLIENT_SCRIPT%
echo Logs: %LOG_DIR%
echo.
echo Useful Commands:
echo   Check status: sc query %SERVICE_NAME%
echo   Stop service: C:\nssm\win64\nssm.exe stop %SERVICE_NAME%
echo   Start service: C:\nssm\win64\nssm.exe start %SERVICE_NAME%
echo   Restart service: C:\nssm\win64\nssm.exe restart %SERVICE_NAME%
echo   View logs: type %LOG_DIR%\service_stdout.log
echo.
echo Service will auto-start on computer boot.
echo.
pause
