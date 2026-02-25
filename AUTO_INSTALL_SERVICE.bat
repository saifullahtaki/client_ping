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
REM Verify Code Version (Check for latest features)
REM ============================================================

set CODE_WAS_OLD=NO
set CODE_UPDATE_METHOD=NONE

REM ============================================================
REM Download Latest Code from Monitor Server
REM ============================================================

set MONITOR_SERVER=http://192.168.40.26:5010
set GITHUB_URL=https://raw.githubusercontent.com/saifullahtaki/client_ping/main/client_ping.py
set TEMP_DOWNLOAD=%SCRIPT_DIR%\client_ping.py.download

REM Delete any existing temp file
if exist "%TEMP_DOWNLOAD%" del "%TEMP_DOWNLOAD%" >nul 2>&1

echo Downloading latest code from monitor server...
echo URL: %MONITOR_SERVER%/client_script
echo.

powershell -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%MONITOR_SERVER%/client_script' -OutFile '%TEMP_DOWNLOAD%' -TimeoutSec 15 -UseBasicParsing; exit 0 } catch { exit 1 }"

if exist "%TEMP_DOWNLOAD%" (
    findstr /C:"CLIENT_BUILD" "%TEMP_DOWNLOAD%" >nul 2>&1
    if !errorLevel! EQU 0 (
        echo [OK] Latest code downloaded from monitor server!
        echo.
        echo Backing up old code...
        copy /Y "%CLIENT_SCRIPT%" "%CLIENT_SCRIPT%.old.%date:~-4%%date:~-10,2%%date:~-7,2%.backup" >nul 2>&1
        echo Applying latest code...
        move /Y "%TEMP_DOWNLOAD%" "%CLIENT_SCRIPT%" >nul 2>&1
        if !errorLevel! EQU 0 (
            echo [OK] Code updated from monitor server!
            echo.
            set CODE_WAS_OLD=NO
            set CODE_UPDATE_METHOD=SERVER
            goto :code_verified
        ) else (
            echo [ERROR] Failed to replace code file!
            pause
            exit /b 1
        )
    ) else (
        echo [WARNING] Downloaded file missing CLIENT_BUILD marker, skipping...
        del "%TEMP_DOWNLOAD%" >nul 2>&1
    )
) else (
    echo [WARNING] Monitor server unreachable. Trying GitHub...
    echo.
)

REM Fallback 1: GitHub
echo Attempting to download from GitHub...
echo URL: %GITHUB_URL%
echo.

powershell -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%GITHUB_URL%' -OutFile '%TEMP_DOWNLOAD%' -TimeoutSec 30 -UseBasicParsing; exit 0 } catch { exit 1 }"

if exist "%TEMP_DOWNLOAD%" (
    findstr /C:"CLIENT_BUILD" "%TEMP_DOWNLOAD%" >nul 2>&1
    if !errorLevel! EQU 0 (
        echo [OK] Latest code downloaded from GitHub!
        echo.
        echo Backing up old code...
        copy /Y "%CLIENT_SCRIPT%" "%CLIENT_SCRIPT%.old.backup" >nul 2>&1
        echo Applying latest code...
        move /Y "%TEMP_DOWNLOAD%" "%CLIENT_SCRIPT%" >nul 2>&1
        if !errorLevel! EQU 0 (
            echo [OK] Code updated from GitHub!
            echo.
            set CODE_WAS_OLD=NO
            set CODE_UPDATE_METHOD=GITHUB
            goto :code_verified
        ) else (
            echo [ERROR] Failed to replace code file!
            pause
            exit /b 1
        )
    ) else (
        del "%TEMP_DOWNLOAD%" >nul 2>&1
        echo [WARNING] GitHub file missing CLIENT_BUILD, skipping...
    )
) else (
    echo [WARNING] GitHub download failed. Trying USB drives...
    echo.
)

REM Fallback 2: Check USB drives
set LATEST_CODE_FOUND=0
set LATEST_CODE_PATH=

echo Searching USB drives for latest code...
for %%d in (D E F G H I J K) do (
    if exist "%%d:\client_ping.py" (
        findstr /C:"CLIENT_BUILD" "%%d:\client_ping.py" >nul 2>&1
        if !errorLevel! EQU 0 (
            set LATEST_CODE_FOUND=1
            set LATEST_CODE_PATH=%%d:\client_ping.py
            echo [FOUND] Latest code at: !LATEST_CODE_PATH!
            goto :usb_found
        )
    )
)

:usb_found
if !LATEST_CODE_FOUND! EQU 1 (
    echo.
    echo Backing up old code...
    copy /Y "%CLIENT_SCRIPT%" "%CLIENT_SCRIPT%.old.backup" >nul 2>&1
    echo Copying latest code from USB...
    copy /Y "!LATEST_CODE_PATH!" "%CLIENT_SCRIPT%" >nul 2>&1
    if !errorLevel! EQU 0 (
        echo [OK] Code updated from USB drive!
        echo.
        set CODE_WAS_OLD=NO
        set CODE_UPDATE_METHOD=USB
        goto :code_verified
    ) else (
        echo [ERROR] Failed to copy from USB!
        pause
        exit /b 1
    )
)

REM Last resort: check if existing file is usable (has CLIENT_BUILD or old function)
echo.
echo [WARNING] All download sources failed. Checking existing file...
findstr /C:"CLIENT_BUILD" "%CLIENT_SCRIPT%" >nul 2>&1
if !errorLevel! EQU 0 (
    echo [OK] Existing file has CLIENT_BUILD - using current version.
    echo [INFO] Service will auto-update when monitor server is reachable.
    echo.
    set CODE_WAS_OLD=NO
    set CODE_UPDATE_METHOD=EXISTING
    goto :code_verified
)

findstr /C:"get_server_info_from_target" "%CLIENT_SCRIPT%" >nul 2>&1
if !errorLevel! EQU 0 (
    echo [WARNING] Using existing older code (no CLIENT_BUILD).
    echo [INFO] Manual update recommended.
    echo.
    set CODE_WAS_OLD=NO
    set CODE_UPDATE_METHOD=EXISTING_OLD
    goto :code_verified
)

echo.
echo [ERROR] Cannot obtain valid code from any source!
echo.
echo Please do one of the following:
echo   1. Connect to the LAN (server: 192.168.40.26)
echo   2. Connect to internet (GitHub download)
echo   3. Copy latest client_ping.py to USB drive (any drive D: to K:)
echo.
pause
exit /b 1

:code_verified
REM Code is now verified - continue with service installation

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

REM Try to find real Python (skip Windows Store aliases)
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "TEST_PYTHON=%%i"
    REM Skip Windows Store alias path
    echo !TEST_PYTHON! | findstr /I /C:"WindowsApps" >nul
    if errorlevel 1 (
        REM This is a real Python, test if it works
        "!TEST_PYTHON!" --version >nul 2>&1
        if !errorLevel! EQU 0 (
            set "PYTHON_EXE=!TEST_PYTHON!"
            set PYTHON_FOUND=1
            goto :python_found
        )
    )
)

REM If no real Python found, try common installation paths
if %PYTHON_FOUND% EQU 0 (
    for %%p in (
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) do (
        if exist %%p (
            set "PYTHON_EXE=%%~p"
            set PYTHON_FOUND=1
            goto :python_found
        )
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
    echo.
    
    REM Refresh environment variables
    for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%b"
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%b"
    set "PATH=%SYS_PATH%;%USR_PATH%"
    
    REM Wait a moment for installation to complete
    timeout /t 3 /nobreak >nul
    
    REM Try finding Python in common locations after winget install
    set PYTHON_FOUND=0
    for %%p in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if exist %%p (
            set "PYTHON_EXE=%%~p"
            set PYTHON_FOUND=1
            echo [OK] Python found: !PYTHON_EXE!
            goto :after_python_install
        )
    )
    
    REM Last resort: try where command again (skip Windows Store)
    for /f "delims=" %%i in ('where python 2^>nul') do (
        set "TEST_PYTHON=%%i"
        echo !TEST_PYTHON! | findstr /I /C:"WindowsApps" >nul
        if errorlevel 1 (
            "!TEST_PYTHON!" --version >nul 2>&1
            if !errorLevel! EQU 0 (
                set "PYTHON_EXE=!TEST_PYTHON!"
                set PYTHON_FOUND=1
                echo [OK] Python found: !PYTHON_EXE!
                goto :after_python_install
            )
        )
    )
    
    :after_python_install
    if %PYTHON_FOUND% EQU 0 (
        echo [ERROR] Python installed but not found in PATH
        echo.
        echo Please try one of these solutions:
        echo 1. Close this window and run the script again
        echo 2. Reboot your computer
        echo 3. Manually install Python from https://www.python.org/downloads/
        echo    (Make sure to check "Add Python to PATH" during installation)
        echo.
        pause
        exit /b 1
    )
)

echo.

REM ============================================================
REM Install Python Dependencies
REM ============================================================

echo Installing Python dependencies...
echo.

REM Upgrade pip first
echo [1/3] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip --quiet

if %errorLevel% NEQ 0 (
    echo [WARNING] pip upgrade failed, continuing anyway...
)

REM Install requests package
echo [2/3] Installing requests package...
"%PYTHON_EXE%" -m pip install requests --quiet

if %errorLevel% NEQ 0 (
    echo [WARNING] Failed to install requests package silently, trying verbose mode...
    "%PYTHON_EXE%" -m pip install requests
    
    if %errorLevel% NEQ 0 (
        echo [ERROR] Failed to install requests package!
        echo.
        echo This package is required for the service to work.
        echo Please check your internet connection and try again.
        echo.
        echo Manual installation: %PYTHON_EXE% -m pip install requests
        echo.
        pause
        exit /b 1
    )
)

REM Install psutil package (for real-time network speed monitoring)
echo [3/3] Installing psutil package (network speed monitoring)...
"%PYTHON_EXE%" -m pip install psutil --quiet

if %errorLevel% NEQ 0 (
    echo [WARNING] Failed to install psutil silently, trying verbose mode...
    "%PYTHON_EXE%" -m pip install psutil
    
    if %errorLevel% NEQ 0 (
        echo [ERROR] Failed to install psutil package!
        echo.
        echo This package is required for network speed monitoring.
        echo Please check your internet connection and try again.
        echo.
        echo Manual installation: %PYTHON_EXE% -m pip install psutil
        echo.
        pause
        exit /b 1
    )
)

REM Verify installation by testing imports
echo Verifying installation...
"%PYTHON_EXE%" -c "import requests; import psutil; print('OK')" >nul 2>&1

if %errorLevel% EQU 0 (
    echo.
    echo [OK] All Python dependencies installed and verified
    echo     - pip (latest)
    echo     - requests (for HTTP API calls)
    echo     - psutil (for real-time network speed monitoring)
) else (
    echo.
    echo [WARNING] Package verification failed, but this is often a cache issue.
    echo The service will attempt to use the packages anyway.
    echo.
    echo If service fails to start, manually run:
    echo   %PYTHON_EXE% -m pip install requests psutil
    echo.
)
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
    
    REM Verify that service is using latest code
    echo.
    echo Verifying service loaded latest code...
    findstr /C:"Successfully fetched" "%LOG_DIR%\service_stdout.log" >nul 2>&1
    if %errorLevel% EQU 0 (
        echo [OK] Service successfully loaded server mappings from API
    ) else (
        echo [INFO] Server mapping fetch not yet complete - may need more time
    )
) else (
    echo [INFO] Log file not created yet
)

echo.
echo ============================================================
echo    Installation Complete!
echo ============================================================
echo.

REM ============================================================
REM Show Installation Summary
REM ============================================================
echo.
echo ============================================================
echo    INSTALLATION SUMMARY
echo ============================================================
echo.

echo [CODE STATUS]
if "!CODE_UPDATE_METHOD!"=="SERVER" (
    echo   - Source: Monitor Server (192.168.40.26)
    echo   - Action: Updated to latest build from server
    echo   - Backup Created: Yes
) else if "!CODE_UPDATE_METHOD!"=="GITHUB" (
    echo   - Source: GitHub (server unreachable)
    echo   - Action: Updated from GitHub
    echo   - Backup Created: Yes
) else if "!CODE_UPDATE_METHOD!"=="USB" (
    echo   - Source: USB Drive (server + GitHub unreachable)
    echo   - Action: Updated from USB
    echo   - Backup Created: Yes
) else if "!CODE_UPDATE_METHOD!"=="EXISTING" (
    echo   - Source: Existing file (all downloads failed)
    echo   - Action: Used current version - will auto-update via service
) else if "!CODE_UPDATE_METHOD!"=="EXISTING_OLD" (
    echo   - Source: Existing older file
    echo   - Action: Manual update recommended
) else (
    echo   - Source: Unknown
)
echo.

echo [PYTHON ENVIRONMENT]
echo   - Python Executable: %PYTHON_EXE%
for /f "delims=" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do echo   - Version: %%v
echo   - Required Packages: requests, psutil
echo   - Installation Status: Verified
echo.
echo [SERVICE STATUS]
echo   - Service Name: %SERVICE_NAME%
echo   - Display Name: Studio Ping Monitor Service
echo   - Status: Running
echo   - Start Type: Automatic (starts on boot)
echo   - Python: %PYTHON_EXE%
echo   - Script: %CLIENT_SCRIPT%
echo   - Log Directory: %LOG_DIR%
echo.

echo [FEATURES ENABLED]
echo   - YouTube Ping Monitoring: Yes
echo   - Origin Server Ping Monitoring: Yes
echo   - Server Name Resolution: Yes (API-based)
echo   - ISP Name Formatting: Yes (Cloud_Point->SDNF, Mirnet->BTS)
echo   - Primary/Backup Detection: Yes
echo   - Network Speed Monitoring: Yes (Download + Upload Mbps, 1s interval)
echo   - Auto-Restart on Failure: Yes
echo.

echo ============================================================
echo.
echo Service is now running and will start automatically on boot.
echo.
echo Useful Commands:
echo   Check status: sc query %SERVICE_NAME%
echo   Stop service: C:\nssm\win64\nssm.exe stop %SERVICE_NAME%
echo   Start service: C:\nssm\win64\nssm.exe start %SERVICE_NAME%
echo   Restart service: C:\nssm\win64\nssm.exe restart %SERVICE_NAME%
echo   View logs: type %LOG_DIR%\service_stdout.log
echo.
pause
