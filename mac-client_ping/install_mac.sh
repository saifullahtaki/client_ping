#!/bin/bash
# ============================================================
# Auto-Install Studio Ping Agent for macOS — Complete Setup
# Run with: sudo ./install_mac.sh
#
# Mac equivalent of AUTO_INSTALL_SERVICE.bat (which uses NSSM on Windows).
# macOS has no NSSM — the standard way to run a background daemon that
# auto-starts at boot and auto-restarts on crash is launchd, so this installs
# a LaunchDaemon (runs as root — required for the MTR feature's raw ICMP
# sockets, same reason the Windows service runs as LocalSystem).
#
# This script tries hard to be a genuine one-shot installer (auto-installs
# Xcode Command Line Tools for python3 if missing, installs pip packages,
# and verifies the daemon is actually alive before declaring success) — but
# no script can be a 100% unconditional guarantee on every possible Mac.
# Corporate MDM restrictions, no internet access, or a completely locked-down
# machine can still block a step. That's why every step below prints a clear
# [OK]/[ERROR] and the final section tells you plainly whether it actually
# worked, instead of just assuming so.
# ============================================================

set -u

FAILED=0
fail() { echo "[ERROR] $1"; FAILED=1; }

echo ""
echo "============================================================"
echo "   Studio Ping Agent - macOS Auto Installer"
echo "============================================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] This script must be run with sudo:"
    echo "        sudo ./install_mac.sh"
    exit 1
fi
echo "[OK] Running as root"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_SCRIPT_SRC="$SCRIPT_DIR/client_ping_mac.py"

if [ ! -f "$CLIENT_SCRIPT_SRC" ]; then
    echo "[ERROR] client_ping_mac.py not found next to this script at: $CLIENT_SCRIPT_SRC"
    exit 1
fi
echo "[OK] Found client_ping_mac.py"
echo ""

INSTALL_DIR="/Library/Application Support/StudioPing"
LOG_DIR="$INSTALL_DIR/logs"
CLIENT_SCRIPT="$INSTALL_DIR/client_ping_mac.py"
LABEL="com.studioping.agent"
PLIST_PATH="/Library/LaunchDaemons/$LABEL.plist"

echo "Install directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" || { fail "could not create $INSTALL_DIR"; exit 1; }
mkdir -p "$LOG_DIR"      || { fail "could not create $LOG_DIR"; exit 1; }
echo "[OK] Directories ready"
echo ""

cp "$CLIENT_SCRIPT_SRC" "$CLIENT_SCRIPT" || { fail "could not copy client_ping_mac.py into $INSTALL_DIR"; exit 1; }
echo "[OK] Installed client_ping_mac.py to $CLIENT_SCRIPT"
echo ""

# ============================================================
# Python 3 — auto-install Xcode Command Line Tools if missing
# (CLT provides /usr/bin/python3 on stock macOS with no Homebrew needed)
# ============================================================
echo "Checking Python 3..."
SYSTEM_PYTHON3="$(command -v python3 || true)"
PYTHON3="$SYSTEM_PYTHON3"

if [ -z "$PYTHON3" ]; then
    echo "[INFO] python3 not found — attempting silent Xcode Command Line Tools install..."
    echo "       (this can take a few minutes; needs internet access)"

    # Standard trick to make `softwareupdate` list + install CLT without popping
    # up the interactive GUI installer.
    touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    CLT_PACKAGE="$(softwareupdate -l 2>/dev/null | grep -B 1 -E "Command Line Tools" | awk -F"\* " '{print $2}' | sed -n '2p')"
    if [ -z "$CLT_PACKAGE" ]; then
        CLT_PACKAGE="$(softwareupdate -l 2>/dev/null | grep "\*.*Command Line Tools" | tail -n 1 | sed 's/^[^C]*//')"
    fi

    if [ -n "$CLT_PACKAGE" ]; then
        echo "  Installing: $CLT_PACKAGE"
        softwareupdate -i "$CLT_PACKAGE" --verbose || true
    else
        echo "  [WARN] Could not find Command Line Tools via softwareupdate."
    fi
    rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress

    PYTHON3="$(command -v python3 || true)"

    if [ -z "$PYTHON3" ]; then
        echo "  [WARN] Silent install did not produce python3 — trying the interactive installer."
        echo "         A popup may appear on this Mac's screen; click 'Install' there if so."
        xcode-select --install 2>&1 || true
        echo ""
        echo "  Waiting up to 5 minutes for python3 to appear after Command Line Tools installs..."
        for i in $(seq 1 30); do
            sleep 10
            PYTHON3="$(command -v python3 || true)"
            [ -n "$PYTHON3" ] && break
            echo "  ...still waiting ($((i*10))s)"
        done
    fi
fi

if [ -z "$PYTHON3" ]; then
    fail "python3 still not available after auto-install attempts."
    echo "  Install manually:  xcode-select --install"
    echo "  or download from:  https://www.python.org/downloads/"
    echo "  then re-run:       sudo ./install_mac.sh"
    exit 1
fi
SYSTEM_PYTHON3="$PYTHON3"
echo "[OK] Found Python: $SYSTEM_PYTHON3"
"$SYSTEM_PYTHON3" --version
echo ""

# ============================================================
# Dedicated virtual environment for the agent's dependencies.
# Modern macOS Python (Homebrew, python.org installer, and recent Xcode CLT)
# refuses system-wide `pip install` with "externally-managed-environment"
# (PEP 668). A venv sidesteps that cleanly and keeps these deps isolated from
# anything else on the machine — this is what Apple/Homebrew's own error
# message recommends.
# ============================================================
VENV_DIR="$INSTALL_DIR/venv"
echo "Setting up virtual environment at $VENV_DIR ..."
if [ ! -x "$VENV_DIR/bin/python3" ]; then
    "$SYSTEM_PYTHON3" -m venv "$VENV_DIR" || { fail "failed to create venv at $VENV_DIR"; exit 1; }
fi
PYTHON3="$VENV_DIR/bin/python3"

if [ ! -x "$PYTHON3" ]; then
    fail "venv python3 not found at $PYTHON3 after venv creation"
    exit 1
fi
echo "[OK] Using venv Python: $PYTHON3"
"$PYTHON3" --version
echo ""

if ! "$PYTHON3" -m pip --version >/dev/null 2>&1; then
    echo "pip not found in venv — bootstrapping via ensurepip..."
    "$PYTHON3" -m ensurepip --upgrade || fail "ensurepip failed"
fi

echo "Installing Python dependencies (requests, psutil, icmplib) into the venv..."
"$PYTHON3" -m pip install --quiet --upgrade pip
if ! "$PYTHON3" -m pip install --quiet requests psutil icmplib; then
    fail "pip install of requests/psutil/icmplib failed — check internet access / pip output above"
fi

echo "Verifying dependencies actually import..."
if "$PYTHON3" -c "import requests, psutil, icmplib" 2>/tmp/studioping_import_check.log; then
    echo "[OK] Python dependencies installed and importable"
else
    fail "one or more dependencies failed to import:"
    cat /tmp/studioping_import_check.log
fi
rm -f /tmp/studioping_import_check.log
echo ""

if [ "$FAILED" -eq 1 ]; then
    echo "[ERROR] Stopping before installing the daemon — fix the errors above and re-run."
    exit 1
fi

# ============================================================
# Configuration — AGENT_NAME / SERVER_URL become launchd
# EnvironmentVariables entries (equivalent to NSSM AppEnvironmentExtra)
# ============================================================
echo "Configuration (press Enter to use the default for each):"
read -p "  AGENT_NAME [default: this Mac's hostname]: " AGENT_NAME_INPUT
read -p "  SERVER_URL [default: http://ostreamping.ums.team:5010]: " SERVER_URL_INPUT
echo ""

ENV_XML=""
if [ -n "$AGENT_NAME_INPUT" ]; then
    ENV_XML="$ENV_XML
        <key>AGENT_NAME</key>
        <string>$AGENT_NAME_INPUT</string>"
fi
if [ -n "$SERVER_URL_INPUT" ]; then
    ENV_XML="$ENV_XML
        <key>SERVER_URL</key>
        <string>$SERVER_URL_INPUT</string>"
fi

EFFECTIVE_SERVER_URL="${SERVER_URL_INPUT:-http://ostreamping.ums.team:5010}"

# ============================================================
# Connectivity check (informational — doesn't block install; the agent
# retries in the background regardless)
# ============================================================
echo "Checking connectivity to $EFFECTIVE_SERVER_URL ..."
HTTP_CODE="$(curl -s -o /dev/null -m 8 -w "%{http_code}" "$EFFECTIVE_SERVER_URL/get_client_ip" || echo "000")"
if [ "$HTTP_CODE" = "200" ]; then
    echo "[OK] Server reachable (HTTP $HTTP_CODE)"
else
    echo "[WARN] Server did not respond as expected (HTTP $HTTP_CODE)."
    echo "       The agent will keep retrying in the background once installed — this"
    echo "       is just a heads-up in case this Mac needs a VPN/firewall rule opened."
fi
echo ""

# ============================================================
# Remove existing daemon (if any) before reinstalling
# ============================================================
if [ -f "$PLIST_PATH" ]; then
    echo "Existing agent found - stopping it..."
    launchctl bootout system "$PLIST_PATH" 2>/dev/null || true
    echo "[OK] Old agent stopped"
    echo ""
fi

# ============================================================
# Write the LaunchDaemon plist
# ============================================================
echo "Writing LaunchDaemon: $PLIST_PATH"
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON3</string>
        <string>$CLIENT_SCRIPT</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>$ENV_XML
    </dict>

    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/service_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/service_stderr.log</string>
</dict>
</plist>
PLIST

chown root:wheel "$PLIST_PATH"
chmod 644 "$PLIST_PATH"
echo "[OK] LaunchDaemon written"
echo ""

# ============================================================
# Load and start
# ============================================================
echo "Starting agent..."
if ! launchctl bootstrap system "$PLIST_PATH"; then
    fail "launchctl bootstrap failed — see output above"
fi
launchctl enable "system/$LABEL" 2>/dev/null || true
echo ""

# ============================================================
# Verify it's ACTUALLY running (not just "the command didn't error")
# ============================================================
echo "============================================================"
echo "   Verification"
echo "============================================================"

RUNNING=0
for i in 1 2 3 4 5; do
    sleep 2
    if launchctl print "system/$LABEL" 2>/dev/null | grep -q "state = running"; then
        RUNNING=1
        break
    fi
done

if [ "$RUNNING" -eq 1 ]; then
    echo "[OK] Daemon is running (state = running)"
else
    fail "daemon did not reach 'running' state after 10s"
    echo "  --- launchctl print output ---"
    launchctl print "system/$LABEL" 2>&1 || true
fi
echo ""

if [ -f "$LOG_DIR/service_stdout.log" ] && grep -q "Mac Agent starting" "$LOG_DIR/service_stdout.log" 2>/dev/null; then
    echo "[OK] Agent logged a successful startup message"
else
    echo "[WARN] Startup message not seen yet in stdout log — this can be normal in the"
    echo "       first few seconds. Check again shortly with the Logs command below."
fi
echo ""

if [ -s "$LOG_DIR/service_stderr.log" ]; then
    echo "[WARN] stderr log is non-empty — showing last 20 lines (may just be startup noise):"
    tail -n 20 "$LOG_DIR/service_stderr.log"
    echo ""
fi

echo "--- Last 15 lines of stdout log ---"
tail -n 15 "$LOG_DIR/service_stdout.log" 2>/dev/null || echo "(no stdout log yet)"
echo ""

echo "============================================================"
if [ "$FAILED" -eq 0 ] && [ "$RUNNING" -eq 1 ]; then
    echo "   Installation Complete — Agent Is Running"
else
    echo "   Installation Finished WITH PROBLEMS — see [ERROR]/[WARN] above"
fi
echo "============================================================"
echo ""
echo "Label:   $LABEL"
echo "Python:  $PYTHON3"
echo "Script:  $CLIENT_SCRIPT"
echo "Logs:    $LOG_DIR"
echo ""
echo "Useful commands:"
echo "  Status:  sudo launchctl print system/$LABEL"
echo "  Stop:    sudo launchctl bootout system \"$PLIST_PATH\""
echo "  Start:   sudo launchctl bootstrap system \"$PLIST_PATH\""
echo "  Logs:    tail -f \"$LOG_DIR/service_stdout.log\""
echo ""
echo "OBS state is read directly from the obs-icr-restreamer plugin's own files"
echo "(~/Library/Application Support/obs-studio/basic/profiles/<profile>/obs-icr-restreamer.json)"
echo ""
echo "Agent will auto-start on boot and auto-restart if it crashes."
echo ""

if [ "$FAILED" -eq 1 ] || [ "$RUNNING" -eq 0 ]; then
    exit 1
fi
