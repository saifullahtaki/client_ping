import time, requests, subprocess, os, threading, platform, socket, sys, json, shutil, math, re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import psutil

# =====================================================================================
#  client_ping_mac.py  —  macOS agent (Windows client is client_ping.py)
#
#  Same job as the Windows client: detect OBS streaming state, ping the streaming
#  targets, collect CPU/RAM/GPU/network stats, and push everything to the Flask
#  server (app.py) which writes it to InfluxDB for Grafana. Only the platform-specific
#  plumbing differs — see the notes below.
# =====================================================================================

CLIENT_BUILD = 1              # Independent version counter for this Mac client file
UPDATE_CHECK_INTERVAL = 20

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if platform.system() != "Darwin":
    print(f"[WARN] client_ping_mac.py is built for macOS, not {platform.system()}. "
          f"Use client_ping.py on Windows.")

# ---------------- macOS OBS state detection ----------------
# On Windows, a custom OBS plugin writes live streaming state into the registry
# (HKCU\Environment\OBS_*) and client_ping.py re-reads the registry every poll cycle.
#
# The macOS equivalent plugin — "obs-icr-restreamer" (a customized fork of the open-source
# obs-multi-rtmp plugin, bundle id net.sorayuki.obs-multi-rtmp) — tries to call
# setEnvironmentVariable() for the same OBS_* names, but on POSIX systems that only reaches
# the *calling process's own environment*, not a shared cross-process store like the
# Windows registry — so nothing else can ever observe it that way, regardless of privilege
# level (confirmed empirically: `launchctl getenv` shows nothing in any domain).
#
# The plugin ALSO writes its full configuration straight to disk, which is what this script
# actually reads:
#   ~/Library/Application Support/obs-studio/user.ini
#       -> [Basic] Profile=<name>                       (which profile is active)
#   ~/Library/Application Support/obs-studio/basic/profiles/<name>/obs-icr-restreamer.json
#       -> stream_config.icrObsCode                     (ICR code)
#       -> stream_config.streamName                      (stream id)
#       -> targets[].service-param.server                (rtmp://host[:port][/path] per destination)
#       -> targets[].playback                            (preview URL per destination)
#
# This agent runs as root (LaunchDaemon, needed for MTR's raw ICMP sockets) which lives in
# a separate launchd "system" domain, isolated from the logged-in user's "gui"/"user"
# domains — so it could never see an interactively-set env var anyway. Reading the
# plugin's own files on disk sidesteps all of that.
_OBS_PLUGIN_VERSION_CACHE = {"path": None, "version": "unknown"}

def _get_console_user():
    """Currently logged-in GUI user (owner of /dev/console). None if nobody's logged in."""
    try:
        result = subprocess.run(["stat", "-f", "%Su", "/dev/console"], capture_output=True, text=True, timeout=5)
        user = result.stdout.strip()
        if user and user != "root":
            return user
    except Exception:
        pass
    return None

def _get_obs_studio_dir():
    user = _get_console_user()
    return f"/Users/{user}/Library/Application Support/obs-studio" if user else None

def _get_active_obs_profile(obs_dir):
    """Read [Basic] Profile= out of user.ini — whichever OBS profile is selected in the UI right now."""
    try:
        with open(os.path.join(obs_dir, "user.ini"), "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'\[Basic\](.*?)(\n\[|\Z)', content, re.DOTALL)
        if m:
            pm = re.search(r'^Profile\s*=\s*(.+)$', m.group(1), re.MULTILINE)
            if pm:
                return pm.group(1).strip()
    except Exception:
        pass
    return None

def _read_icr_plugin_config(obs_dir, profile):
    """Read the obs-icr-restreamer plugin's own settings file for the active profile."""
    path = os.path.join(obs_dir, "basic", "profiles", profile, "obs-icr-restreamer.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig strips the file's BOM
            return json.load(f)
    except Exception:
        return None

def _get_obs_plugin_version(obs_dir):
    """Read the plugin bundle's own version via `plutil` (avoids adding a plist-parsing dependency)."""
    plist_path = os.path.join(obs_dir, "plugins", "obs-icr-restreamer.plugin", "Contents", "Info.plist")
    if _OBS_PLUGIN_VERSION_CACHE["path"] == plist_path:
        return _OBS_PLUGIN_VERSION_CACHE["version"]
    version = "unknown"
    try:
        result = subprocess.run(
            ["plutil", "-extract", "CFBundleShortVersionString", "raw", plist_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            version = result.stdout.strip()
    except Exception:
        pass
    _OBS_PLUGIN_VERSION_CACHE["path"] = plist_path
    _OBS_PLUGIN_VERSION_CACHE["version"] = version
    return version

def _extract_rtmp_host(server_url):
    """rtmp://host:port/app -> host"""
    if not server_url:
        return ""
    return server_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]

def _read_obs_icr_state():
    """
    Pull everything the obs-icr-restreamer plugin knows for the active profile.
    Returns "unknown"/empty values if OBS isn't configured with this plugin yet, or
    nobody's logged into the GUI session.
    """
    result = {"icr_code": "unknown", "stream_name": "", "servers": [], "previews": [], "plugin_version": "unknown"}
    obs_dir = _get_obs_studio_dir()
    if not obs_dir:
        return result

    result["plugin_version"] = _get_obs_plugin_version(obs_dir)

    profile = _get_active_obs_profile(obs_dir)
    if not profile:
        return result

    config = _read_icr_plugin_config(obs_dir, profile)
    if not config:
        return result

    stream_config = config.get("stream_config", {}) or {}
    result["icr_code"] = stream_config.get("icrObsCode") or "unknown"
    result["stream_name"] = stream_config.get("streamName") or ""

    for t in (config.get("targets") or []):
        service_param = t.get("service-param", {}) or {}
        host = _extract_rtmp_host(service_param.get("server", ""))
        if host and host not in result["servers"]:
            result["servers"].append(host)
        playback = t.get("playback") or ""
        if playback:
            result["previews"].append(playback)

    return result

def get_setting(name, default=""):
    """Read a runtime setting from the process environment, set via the launchd plist —
    the same role NSSM's AppEnvironmentExtra plays on Windows. OBS state is NOT read this
    way — see _read_obs_icr_state() and the notes above for why."""
    return os.environ.get(name, default)

SERVER_URL = get_setting("SERVER_URL", "http://ostreamping.ums.team:5010")

def get_agent_name():
    agent = get_setting("AGENT_NAME", "")
    if agent:
        return agent
    try:
        hostname = socket.gethostname()
        # macOS hostnames are typically "Somes-MacBook-Pro.local" — strip the suffix
        if hostname.endswith(".local"):
            hostname = hostname[:-len(".local")]
        return hostname
    except Exception:
        return "unknown-agent"

AGENT_NAME = get_agent_name()

# Global variables to store client info
client_local_ip = "unknown"
client_public_ip = "unknown"
client_isp_name = "unknown"

# Global variables for real-time network speed (updated every second)
network_download_mbps = 0.0
network_upload_mbps = 0.0

# GPU name only on macOS — see the GPU section below for why usage % isn't collected
_gpu_usage = 0.0
_gpu_name = "unknown"

# On-demand MTR: specific target currently selected in Grafana for this PC (None = off)
_on_demand_target = None

# Global variables to store OBS streaming data
obs_icr_code = "unknown"
obs_stream_title = "unknown"
obs_stream_preview_ostream = "unknown"
obs_stream_preview_youtube = "unknown"
obs_plugin_version = "unknown"

# Setup logging for daemon mode
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# RotatingFileHandler: max 500KB per file, keep 2 backups = 1MB total max
LOG_FILE = os.path.join(LOG_DIR, "client_ping_mac.log")
_logger = logging.getLogger("client_ping_mac")
_logger.setLevel(logging.INFO)
_handler = RotatingFileHandler(LOG_FILE, maxBytes=500*1024, backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)

def cleanup_old_logs(days=7):
    """Delete any .log files in the logs folder older than `days` days."""
    try:
        cutoff = time.time() - days * 86400
        for fname in os.listdir(LOG_DIR):
            if not fname.endswith(".log") and not fname.endswith(".log.1") and not fname.endswith(".log.2"):
                continue
            fpath = os.path.join(LOG_DIR, fname)
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
    except Exception:
        pass

def log_cleanup_loop():
    """Background thread: clean up old logs once a day."""
    cleanup_old_logs()   # run once on startup
    while True:
        time.sleep(86400)  # 24 hours
        cleanup_old_logs()

def log_print(message):
    """Print to both console and log file with timestamp."""
    timestamp = datetime.now().isoformat()
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    sys.stdout.flush()  # Important for daemon mode
    _logger.info(log_msg)

def format_display_name(name, name_type="target"):
    """Format display names for better readability in Grafana.

    For targets: Remove .udvashunmesh.com suffix
    For ISPs: Shorten common ISP names
    """
    if not name or name == "unknown":
        return name

    if name_type == "target":
        if ".udvashunmesh.com" in name.lower():
            name = name.split(".udvashunmesh.com")[0]
        return name

    elif name_type == "isp":
        isp_mappings = {
            "Link3_Technologies_Limited": "Link3",
            "Link3 Technologies Limited": "Link3",
            "Bangladesh_Online_Ltd": "BOL",
            "Bangladesh Online Ltd": "BOL",
            "Cloud_Point": "SDNF",
            "Cloud Point": "SDNF",
            "Amber_IT_Limited": "AmberIT",
            "Amber IT Limited": "AmberIT",
            "Mirnet": "BTS",
            "Mirnet_Limited": "BTS",
            "Mirnet Limited": "BTS",
            "BTS_Communications_(BD)_Ltd": "BTS",
            "BTS Communications (BD) Ltd": "BTS",
            "BTS_Communications": "BTS",
            "BTS Communications": "BTS"
        }
        return isp_mappings.get(name, name)

    return name

def resolve_target_to_ip(target):
    """Resolve hostname/target to IP address."""
    try:
        ip_address = socket.gethostbyname(target)
        return ip_address
    except Exception:
        try:
            socket.inet_aton(target)
            return target  # It's already an IP
        except Exception:
            return None

# ---------------- Network Detection ----------------
def get_local_ip():
    """Detect local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to Google DNS
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "unknown"

def detect_obs_streaming_data():
    """Detect OBS streaming data from the obs-icr-restreamer plugin's own config files."""
    global obs_icr_code, obs_stream_title, obs_stream_preview_ostream, obs_stream_preview_youtube, obs_plugin_version

    try:
        state = _read_obs_icr_state()
        obs_plugin_version = state["plugin_version"]
        obs_icr_code = state["icr_code"]
        obs_stream_title = "unknown"  # not exposed by this plugin's config file

        obs_stream_preview_ostream = "unknown"
        obs_stream_preview_youtube = "unknown"

        for url in state["previews"]:
            if 'youtube' in url.lower() or 'youtu.be' in url.lower():
                obs_stream_preview_youtube = url
            elif 'ostream' in url.lower():
                obs_stream_preview_ostream = url
            else:
                if obs_stream_preview_ostream == "unknown":
                    obs_stream_preview_ostream = url
                elif obs_stream_preview_youtube == "unknown":
                    obs_stream_preview_youtube = url

        log_print(f"OBS Streaming Data Detected: Plugin Version={obs_plugin_version}, ICR Code={obs_icr_code}, Title={obs_stream_title}")
        log_print(f"  Preview URLs - OStream={obs_stream_preview_ostream}, YouTube={obs_stream_preview_youtube}")
        return True
    except Exception as e:
        log_print(f"Failed to detect OBS streaming data: {e}")
        return False

def detect_client_info():
    """Detect local IP, public IP, and ISP name."""
    global client_local_ip, client_public_ip, client_isp_name

    client_local_ip = get_local_ip()

    try:
        res = requests.get("https://api.ipify.org?format=json", timeout=10)
        client_public_ip = res.json().get("ip", "unknown")

        isp_res = requests.get(f"http://ip-api.com/json/{client_public_ip}", timeout=10)
        isp_json = isp_res.json()
        if isp_json.get("status") == "success":
            client_isp_name = isp_json.get("isp", "unknown")

        log_print(f"Client Info Detected: Local IP={client_local_ip}, Public IP={client_public_ip}, ISP={client_isp_name}")
        return True
    except Exception as e:
        log_print(f"Failed to detect client info: {e}")
        return False

# ---------------- OBS Process Detection ----------------
def is_obs_running():
    """Check if OBS is running on macOS. OBS.app's binary is literally named "OBS"."""
    try:
        result = subprocess.run(
            ["pgrep", "-ix", "OBS"],
            capture_output=True, timeout=2
        )
        return result.returncode == 0
    except Exception:
        return False

# Auto-detect targets straight from the obs-icr-restreamer plugin's config
def get_targets_from_config():
    """Re-read the plugin's target list (live value) — hostnames for every configured
    RTMP destination (OStream origin server AND YouTube alike), no URL-guessing needed
    since the plugin's own targets[] array already lists them explicitly."""
    state = _read_obs_icr_state()
    targets = state["servers"]
    if targets:
        log_print(f"Detected OBS servers: {targets}")
    return targets

POLL_INTERVAL = int(get_setting("POLL_INTERVAL", "5"))
PING_INTERVAL = float(get_setting("PING_INTERVAL", "1"))

session = requests.Session()

# ---------------- Parse ping ----------------
def parse_ping_output(output):
    """
    Parse macOS `ping` output and return RTT in ms.
    - Returns -10.0 for Grafana if parsing fails.
    """
    out = output.decode(errors='ignore') if isinstance(output, bytes) else str(output)

    if "time=" not in out:
        return -10.0

    try:
        time_idx = out.find("time=")
        start = time_idx + 5  # len("time=")
        num_str = ''
        for i in range(start, min(start + 10, len(out))):
            ch = out[i]
            if ch.isdigit() or ch == '.':
                num_str += ch
            elif num_str:
                break

        if not num_str:
            return -10.0

        rtt = float(num_str)
        if rtt <= 0:
            return -10.0

        return rtt if rtt >= 1.0 else 1.0
    except (ValueError, IndexError):
        return -10.0

def do_ping_once(target):
    """
    Run one macOS ping.
    NOTE: BSD/macOS `ping -W` is in MILLISECONDS (unlike Linux, where -W is seconds) —
    so it takes the same value the Windows client passes to `-w`.
    """
    if 'youtube' in target.lower() or 'rtmp' in target.lower() or 'facebook' in target.lower():
        timeout_ms = "1500"  # international servers need more time
        timeout_sec = 3
    else:
        timeout_ms = "1000"
        timeout_sec = 2

    cmd = ["ping", "-c", "1", "-W", timeout_ms, str(target)]

    try:
        start_time = time.perf_counter()
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec
        )
        end_time = time.perf_counter()
        out = p.stdout.decode(errors='ignore')

        if p.returncode == 0:
            rtt = parse_ping_output(out)
            if rtt <= 0:
                # Reply came back (returncode 0) but the text couldn't be parsed —
                # fall back to the measured wall-clock time rather than guessing.
                rtt = round((end_time - start_time) * 1000, 2)
            return True, rtt, out
        else:
            return False, -10.0, out

    except subprocess.TimeoutExpired:
        return False, -10.0, "Timeout"
    except Exception as e:
        return False, -10.0, str(e)

# ---------------- Send ping ----------------
def send_ping(target, rtt, success, raw):
    target_ip = resolve_target_to_ip(target)
    stream_id = ""

    if target_ip and ".udvashunmesh.com" in target.lower():
        if obs_stream_preview_ostream and obs_stream_preview_ostream != "unknown":
            try:
                if "streamName=" in obs_stream_preview_ostream:
                    stream_id = obs_stream_preview_ostream.split("streamName=")[1].split("&")[0]
            except Exception:
                pass

        if not stream_id:
            stream_id = target.replace(".udvashunmesh.com", "").replace("os-origin-server-", "")

    if "youtube" in target.lower() and obs_stream_preview_youtube and obs_stream_preview_youtube != "unknown":
        try:
            if "watch?v=" in obs_stream_preview_youtube:
                stream_id = obs_stream_preview_youtube.split("watch?v=")[1].split("&")[0]
        except Exception:
            pass

    target_display = format_display_name(target, "target")
    isp_display = format_display_name(client_isp_name, "isp")

    payload = {
        "client_id": client_local_ip,
        "computer_name": AGENT_NAME,
        "target": target,
        "target_display": target_display,
        "target_ip": target_ip if target_ip else "",
        "stream_id": stream_id,
        "isp": client_isp_name,
        "isp_display": isp_display,
        "preview_ostream": obs_stream_preview_ostream,
        "preview_youtube": obs_stream_preview_youtube,
        "obs_plugin_version": obs_plugin_version,
        "timestamp": int(time.time()),
        "success": success,
        "rtt_ms": rtt,
        "raw": raw[:2000]
    }
    try:
        session.post(SERVER_URL.rstrip("/") + "/push_ping", json=payload, timeout=5)
    except Exception as e:
        log_print(f"Ping send error for {target}: {e}")

# ---------------- Agent version / auto-update ----------------
def push_agent_version():
    """Report this Mac's current build + identity to server for /pc_versions dashboard."""
    try:
        payload = {
            "computer_name": AGENT_NAME,
            "build":         CLIENT_BUILD,
            "local_ip":      client_local_ip,
            "public_ip":     client_public_ip,
            "isp":           client_isp_name,
            "gpu_name":      _gpu_name,
            "platform":      "mac",
        }
        session.post(SERVER_URL.rstrip("/") + "/push_agent_version", json=payload, timeout=5)
    except Exception:
        pass

def check_and_apply_update():
    """
    Check server for a newer build of client_ping_mac.py.
    NOTE: this points at /client_version_mac and /client_script_mac — separate from the
    Windows client's /client_version and /client_script, because those serve the Windows
    file's content, which would crash this process if downloaded here. These mac-specific
    routes don't exist on the server yet; until they're added this simply 404s and no-ops,
    which is safe. Add them (serving a separate client_ping_mac.py copy) to enable
    auto-update for Mac agents.
    """
    try:
        resp = session.get(SERVER_URL.rstrip("/") + "/client_version_mac", timeout=10)
        if resp.status_code != 200:
            return

        server_build = int(resp.json().get("build", 0))

        if server_build <= CLIENT_BUILD:
            return

        log_print(f"[AUTO-UPDATE] New version available! server={server_build}, current={CLIENT_BUILD}")
        log_print(f"[AUTO-UPDATE] Downloading...")

        dl = session.get(SERVER_URL.rstrip("/") + "/client_script_mac", timeout=30)
        if dl.status_code != 200:
            log_print(f"[AUTO-UPDATE] Download failed: HTTP {dl.status_code}")
            return

        new_code = dl.text

        if f"CLIENT_BUILD = {server_build}" not in new_code:
            log_print(f"[AUTO-UPDATE] Verification failed - BUILD number mismatch in downloaded file")
            return

        current_script = os.path.abspath(__file__)
        temp_file = current_script + ".update"
        backup_file = current_script + ".backup"

        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(new_code)

        log_print(f"[AUTO-UPDATE] Downloaded {len(new_code)} bytes OK")

        if os.path.exists(backup_file):
            os.remove(backup_file)
        shutil.copy2(current_script, backup_file)

        shutil.move(temp_file, current_script)

        log_print(f"[AUTO-UPDATE] Applied build {server_build}. Restarting...")
        os._exit(0)   # launchd (KeepAlive) restarts the process, loading the new code

    except Exception as e:
        log_print(f"[AUTO-UPDATE] Error: {e}")

def auto_update_loop():
    """Background thread: wait 5s on startup, then check every UPDATE_CHECK_INTERVAL seconds."""
    time.sleep(5)
    while True:
        check_and_apply_update()
        push_agent_version()
        time.sleep(UPDATE_CHECK_INTERVAL)

# ---------------- Network Speed Monitoring ----------------
def push_network_speed(download_mbps, upload_mbps):
    """Send real-time network speed to server for InfluxDB storage."""
    try:
        isp_display = format_display_name(client_isp_name, "isp")
        payload = {
            "client_id": client_local_ip,
            "computer_name": AGENT_NAME,
            "isp": client_isp_name,
            "isp_display": isp_display,
            "download_mbps": round(download_mbps, 4),
            "upload_mbps": round(upload_mbps, 4),
            "timestamp": int(time.time())
        }
        session.post(SERVER_URL.rstrip("/") + "/push_network_speed", json=payload, timeout=5)
    except Exception:
        pass  # Silent - not critical

def network_speed_loop():
    """
    Background thread: measures real-time network speed every 1 second.
    Uses psutil - same method as Activity Monitor (delta of OS network counters).
    Sends download + upload in Mbps to InfluxDB via server.
    """
    global network_download_mbps, network_upload_mbps

    prev_io = psutil.net_io_counters(pernic=True)
    prev_time = time.perf_counter()

    while True:
        try:
            time.sleep(1)
            curr_io = psutil.net_io_counters(pernic=True)
            curr_time = time.perf_counter()
            elapsed = curr_time - prev_time

            total_sent = 0
            total_recv = 0

            for nic, curr in curr_io.items():
                # Skip loopback interfaces. macOS names it "lo0" (not "lo" like Linux),
                # so a plain "== 'lo'" check misses it entirely.
                if nic.lower() in ('lo', 'lo0') or 'loopback' in nic.lower():
                    continue
                prev = prev_io.get(nic)
                if prev:
                    sent_delta = curr.bytes_sent - prev.bytes_sent
                    recv_delta = curr.bytes_recv - prev.bytes_recv
                    if sent_delta >= 0:
                        total_sent += sent_delta
                    if recv_delta >= 0:
                        total_recv += recv_delta

            download_mbps = (total_recv * 8) / (1_000_000 * elapsed)
            upload_mbps = (total_sent * 8) / (1_000_000 * elapsed)

            download_mbps = max(0.0, round(download_mbps, 4))
            upload_mbps   = max(0.0, round(upload_mbps, 4))

            network_download_mbps = download_mbps
            network_upload_mbps   = upload_mbps

            prev_io   = curr_io
            prev_time = curr_time

            push_network_speed(download_mbps, upload_mbps)

        except Exception as e:
            log_print(f"Network speed error: {e}")
            time.sleep(5)

# ---------------- System Stats (CPU + Memory + GPU) ----------------
def _detect_gpu_name():
    """
    One-time GPU name detection via `system_profiler`.
    GPU *usage* % is intentionally not collected on macOS: Windows gets it from WMI/GPU
    Engine performance counters, but macOS has no equivalent user-space API — the only way
    (powermetrics) needs root and per-sample overhead unsuitable for a 1-second poll loop.
    _gpu_usage is left at 0.0 / unmeasured.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10
        )
        names = re.findall(r"Chipset Model:\s*(.+)", result.stdout)
        if names:
            return "+".join(n.strip() for n in names)
    except Exception:
        pass
    return "unknown"

def push_system_stats(cpu_percent, mem_total_mb, mem_available_mb, mem_used_mb, mem_percent):
    """Send CPU and memory stats to server for InfluxDB storage."""
    try:
        isp_display = format_display_name(client_isp_name, "isp")
        payload = {
            "client_id": client_local_ip,
            "computer_name": AGENT_NAME,
            "isp": client_isp_name,
            "isp_display": isp_display,
            "cpu_percent": cpu_percent,
            "mem_total_mb": mem_total_mb,
            "mem_available_mb": mem_available_mb,
            "mem_used_mb": mem_used_mb,
            "mem_percent": mem_percent,
            "gpu_usage_percent": _gpu_usage,
            "gpu_name": _gpu_name,
            "timestamp": int(time.time())
        }
        session.post(SERVER_URL.rstrip("/") + "/push_system_stats", json=payload, timeout=5)
    except Exception:
        pass  # Silent - not critical

def system_stats_loop():
    """
    Background thread: measures CPU and memory every 1 second.
    Uses psutil - same method as Activity Monitor.
    """
    psutil.cpu_percent(interval=None)  # first call just primes the counter

    while True:
        try:
            time.sleep(1)
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            mem_total_mb     = round(mem.total     / (1024 * 1024), 1)
            mem_available_mb = round(mem.available / (1024 * 1024), 1)
            mem_used_mb      = round(mem.used      / (1024 * 1024), 1)
            mem_percent      = round(mem.percent, 1)
            push_system_stats(cpu, mem_total_mb, mem_available_mb, mem_used_mb, mem_percent)
        except Exception as e:
            log_print(f"System stats error: {e}")
            time.sleep(5)

# =====================================================================================
#  MTR — Continuous My TraceRoute engine
#  Probes each target continuously (one traceroute/sec), accumulates rolling stats
#  per hop, pushes to InfluxDB every 5s.
#  Uses icmplib's raw-ICMP traceroute — this needs root, which is why install_mac.sh
#  installs this as a LaunchDaemon (runs as root) rather than a per-user LaunchAgent.
# =====================================================================================
try:
    from icmplib import traceroute as _icmp_traceroute
    _MTR_AVAILABLE = True
except ImportError:
    try:
        log_print("[MTR] icmplib not found - auto-installing...")
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'icmplib', '-q'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        from icmplib import traceroute as _icmp_traceroute
        _MTR_AVAILABLE = True
        log_print("[MTR] icmplib installed successfully")
    except Exception as _mtr_install_err:
        _MTR_AVAILABLE = False
        log_print(f"[MTR] icmplib unavailable - MTR disabled ({_mtr_install_err})")

MTR_PUSH_INTERVAL = 5   # push accumulated stats to server every N seconds

_mtr_state   = {}  # target -> {hop_num: _HopState}
_mtr_lock    = threading.Lock()
_mtr_threads = {}  # target -> Thread
_mtr_flags   = {}  # target -> {'stop': bool}

_ptr_cache = {}  # ip -> hostname  (PTR lookup cache, never evicted)


class _HopState:
    """Rolling MTR statistics for one hop — same fields as `mtr` output."""
    __slots__ = ['ip', 'hostname', 'snt', 'rcv',
                 'last_ms', 'total_ms', 'total_sq_ms', 'min_ms', 'max_ms']

    def __init__(self, ip):
        self.ip          = ip
        self.hostname    = ip   # will be overwritten by async PTR lookup
        self.snt         = 0
        self.rcv         = 0
        self.last_ms     = 0.0
        self.total_ms    = 0.0
        self.total_sq_ms = 0.0
        self.min_ms      = float('inf')
        self.max_ms      = 0.0

    def record_rtt(self, rtt_ms):
        self.snt         += 1
        self.rcv         += 1
        self.last_ms      = round(rtt_ms, 2)
        self.total_ms    += rtt_ms
        self.total_sq_ms += rtt_ms * rtt_ms
        if rtt_ms < self.min_ms: self.min_ms = rtt_ms
        if rtt_ms > self.max_ms: self.max_ms = rtt_ms

    def record_loss(self):
        self.snt += 1

    @property
    def loss_pct(self):
        return round((self.snt - self.rcv) / self.snt * 100, 1) if self.snt > 0 else 0.0

    @property
    def avg_ms(self):
        return round(self.total_ms / self.rcv, 2) if self.rcv > 0 else 0.0

    @property
    def best_ms(self):
        return round(self.min_ms, 2) if self.rcv > 0 and self.min_ms != float('inf') else 0.0

    @property
    def worst_ms(self):
        return round(self.max_ms, 2) if self.rcv > 0 else 0.0

    @property
    def stdev_ms(self):
        if self.rcv < 2:
            return 0.0
        mean     = self.total_ms / self.rcv
        variance = self.total_sq_ms / self.rcv - mean * mean
        return round(math.sqrt(max(0.0, variance)), 2)


def _ptr_lookup_async(hop, ip):
    """Resolve PTR in a daemon thread, stores result in hop.hostname."""
    def _run():
        if ip in _ptr_cache:
            hop.hostname = _ptr_cache[ip]
            return
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ip
        _ptr_cache[ip] = host
        hop.hostname = host
    threading.Thread(target=_run, daemon=True).start()


def _poll_mtr_demand():
    """
    Background thread: asks server every 15 s which target Grafana has selected
    for this PC. Sets _on_demand_target so mtr_loop knows which target to run.
    """
    global _on_demand_target
    while True:
        try:
            r = session.get(
                SERVER_URL.rstrip('/') + f'/mtr_check/{AGENT_NAME}',
                timeout=5
            )
            data = r.json()
            if data.get('active'):
                _on_demand_target = data.get('target')
            else:
                _on_demand_target = None
        except Exception:
            pass
        time.sleep(15)


def _run_mtr_once(target, max_hops=30):
    """One full MTR probe cycle via icmplib. Returns list of (hop_num, ip, rtt_ms, timed_out)."""
    if not _MTR_AVAILABLE:
        return []
    try:
        hops = _icmp_traceroute(
            target,
            count    = 2,
            interval = 0.05,
            timeout  = 1.0,
            max_hops = max_hops,
            fast     = True,
        )
        results = []
        for h in hops:
            if h.packets_received > 0:
                results.append((h.distance, h.address, h.avg_rtt, False))
            else:
                results.append((h.distance, '*', 0.0, True))
        return results
    except Exception:
        return []


def _push_mtr(target, target_display, hops_snapshot):
    """POST current hop stats to server /push_mtr (non-blocking)."""
    try:
        payload = {
            "computer_name":  AGENT_NAME,
            "target":         target,
            "target_display": target_display,
            "hops":           hops_snapshot,
            "timestamp":      int(time.time()),
            "isp":            client_isp_name,
            "public_ip":      client_public_ip,
        }
        session.post(SERVER_URL.rstrip("/") + "/push_mtr", json=payload, timeout=5)
    except Exception:
        pass


def mtr_loop(target):
    """
    Continuous MTR loop for one target.
    - Sends one full traceroute ~every second (icmplib with count=1).
    - Accumulates rolling stats (loss%, avg, best, worst, stdev, snt).
    - Pushes snapshot to InfluxDB every MTR_PUSH_INTERVAL seconds.
    - Only active while OBS is running (same gate as ping_loop).
    """
    if not _MTR_AVAILABLE:
        return

    target_display = format_display_name(target, "target")
    hops         = {}    # hop_num -> _HopState
    last_push    = 0.0
    demand_start = None  # time when this target was first demanded by Grafana

    while not _mtr_flags.get(target, {}).get('stop', False):
        # ── Gate 1: OBS must be running ──────────────────────────────────────────
        if not is_obs_running():
            demand_start = None
            if hops:
                hops = {}
                with _mtr_lock:
                    _mtr_state[target] = {}
            time.sleep(5)
            continue

        # ── Gate 2: only run for the target Grafana currently has selected ───────
        if _on_demand_target != target_display:
            demand_start = None
            if hops:
                hops = {}
                with _mtr_lock:
                    _mtr_state[target] = {}
            time.sleep(5)
            continue

        # ── Gate 3: 10-second warm-up delay after target is first selected ───────
        if demand_start is None:
            demand_start = time.time()
            log_print(f'[MTR] {target}: selected in Grafana, starting in 10s...')
        if time.time() - demand_start < 10:
            time.sleep(1)
            continue

        # ── One MTR probe cycle ───────────────────────────────────────────────────
        results = _run_mtr_once(target)
        if not results:
            time.sleep(1)
            continue

        # ── Accumulate stats ──────────────────────────────────────────────────────
        current_hop_nums = {r[0] for r in results}
        for stale in [k for k in list(hops.keys()) if k not in current_hop_nums]:
            del hops[stale]

        for hop_num, ip, rtt_ms, timed_out in results:
            if hop_num not in hops:
                hops[hop_num] = _HopState(ip)
                if ip != '*':
                    _ptr_lookup_async(hops[hop_num], ip)
            hop = hops[hop_num]

            if ip != '*' and ip != hop.ip:
                hop.ip = ip
                hop.hostname = ip
                _ptr_lookup_async(hop, ip)

            if timed_out:
                hop.record_loss()
            else:
                hop.record_rtt(rtt_ms)

        with _mtr_lock:
            _mtr_state[target] = dict(hops)

        now = time.time()
        if now - last_push >= MTR_PUSH_INTERVAL:
            last_push = now
            snapshot = []
            for hn, s in sorted(hops.items()):
                snapshot.append({
                    "hop_num":  hn,
                    "hop_ip":   s.ip,
                    "hostname": s.hostname or s.ip,
                    "loss_pct": s.loss_pct,
                    "last_ms":  s.last_ms,
                    "avg_ms":   s.avg_ms,
                    "best_ms":  s.best_ms,
                    "worst_ms": s.worst_ms,
                    "stdev_ms": s.stdev_ms,
                    "snt":      s.snt,
                    "rcv":      s.rcv,
                })
            threading.Thread(
                target=_push_mtr,
                args=(target, target_display, snapshot),
                daemon=True
            ).start()

        time.sleep(0.5)

    with _mtr_lock:
        _mtr_state.pop(target, None)


# ---------------- Push client info ----------------
def push_client_info():
    """Push client info to server using detected values."""
    try:
        obs_running = is_obs_running()

        if obs_running:
            detect_obs_streaming_data()

            streaming_servers = get_targets_from_config()

            os_origin_server = "none"
            youtube_server = "none"
            os_origin_ping = 0.0
            youtube_ping = 0.0

            for target in streaming_servers:
                success, rtt, _ = do_ping_once(target)

                if target.lower().startswith("os-") or "ostream" in target.lower() or "origin" in target.lower():
                    os_origin_server = target
                    os_origin_ping = rtt if success and rtt >= 0 else 0.0
                elif "youtube" in target.lower() or "rtmp" in target.lower():
                    youtube_server = target
                    youtube_ping = rtt if success and rtt >= 0 else 0.0
        else:
            os_origin_server = "none"
            youtube_server = "none"
            os_origin_ping = 0.0
            youtube_ping = 0.0

        payload = {
            "client_id": client_local_ip,
            "computer_name": AGENT_NAME,
            "build": CLIENT_BUILD,
            "local_ip": client_local_ip,
            "public_ip": client_public_ip,
            "isp": client_isp_name,
            "obs_icr_code": obs_icr_code if obs_running else "unknown",
            "obs_stream_title": obs_stream_title if obs_running else "unknown",
            "obs_stream_preview_ostream": obs_stream_preview_ostream if obs_running else "unknown",
            "obs_stream_preview_youtube": obs_stream_preview_youtube if obs_running else "unknown",
            "obs_plugin_version": obs_plugin_version if obs_running else "unknown",
            "os_origin_server": os_origin_server,
            "os_origin_ping": os_origin_ping,
            "youtube_server": youtube_server,
            "youtube_ping": youtube_ping,
            "obs_running": obs_running,
            "platform": "mac",
        }
        session.post(SERVER_URL.rstrip("/") + "/push_client_info", json=payload, timeout=5)

        if obs_running:
            log_print(f"Client info pushed: {client_isp_name} ({client_public_ip}) | ICR: {obs_icr_code} | OStream: {os_origin_server} ({os_origin_ping}ms)")
        else:
            log_print(f"Client info pushed: {client_isp_name} ({client_public_ip}) | OBS: NOT RUNNING - cleared data")
    except Exception as e:
        log_print(f"Failed to push client info: {e}")

# ---------------- Ping Loop ----------------
threads = {}
stop_flags = {}
client_info_counters = {}  # Track when to send client info

def ping_loop(target):
    tf = stop_flags[target]
    client_info_counters[target] = 0

    while not tf['stop']:
        success, rtt, raw = do_ping_once(target)
        send_ping(target, rtt, success, raw)

        client_info_counters[target] += 1
        if client_info_counters[target] >= 60:
            push_client_info()
            client_info_counters[target] = 0

        time.sleep(PING_INTERVAL)

# ---------------- Manage Targets ----------------
def _push_mtr_targets(targets):
    """Push current known targets to server so Grafana Target dropdown is always populated."""
    try:
        payload = {
            "computer_name": AGENT_NAME,
            "targets": list(targets),
        }
        session.post(SERVER_URL.rstrip("/") + "/push_mtr_targets", json=payload, timeout=5)
    except Exception:
        pass


def _drop_mtr_targets():
    """Tell server to drop this PC's mtr_targets series so it disappears from Grafana dropdown."""
    try:
        session.post(SERVER_URL.rstrip("/") + "/drop_mtr_targets",
                     json={"computer_name": AGENT_NAME}, timeout=5)
    except Exception:
        pass


def manage_targets_loop():
    known_targets = set()
    last_env_targets = set()
    last_obs_status = None
    last_targets_push = 0.0

    while True:
        try:
            obs_running = is_obs_running()
        except KeyboardInterrupt:
            log_print("[SHUTDOWN] KeyboardInterrupt received - agent stopping.")
            os._exit(0)
        try:
            if obs_running != last_obs_status:
                if obs_running:
                    log_print("OBS detected - starting to monitor streaming servers")
                else:
                    log_print("OBS not running - stopping all monitoring")
                last_obs_status = obs_running

            current_env_targets = set(get_targets_from_config())

            if obs_running:
                if current_env_targets != last_env_targets:
                    if current_env_targets:
                        log_print(f"OBS targets detected: {', '.join(current_env_targets)}")
                    else:
                        log_print("No OBS targets found in config")
                    last_env_targets = current_env_targets

                new_targets = current_env_targets.copy()
            else:
                new_targets = set()
                if last_env_targets:
                    log_print("Clearing all targets - OBS is closed")
                    last_env_targets = set()
                    last_targets_push = 0.0
                    _drop_mtr_targets()

            if obs_running:
                try:
                    r = session.get(SERVER_URL.rstrip("/") + "/get_targets", timeout=5)
                    if r.status_code == 200:
                        tlist = r.json()
                        server_targets = set([t['target'] for t in tlist])
                        new_targets.update(server_targets)
                except Exception:
                    pass

            if obs_running and new_targets and time.time() - last_targets_push > 30:
                _push_mtr_targets(new_targets)
                last_targets_push = time.time()

            # start new
            for t in new_targets - known_targets:
                stop_flags[t] = {'stop': False}
                th = threading.Thread(target=ping_loop, args=(t,), daemon=True)
                threads[t] = th
                th.start()
                if _MTR_AVAILABLE:
                    _mtr_flags[t]   = {'stop': False}
                    mtr_th = threading.Thread(target=mtr_loop, args=(t,), daemon=True)
                    _mtr_threads[t] = mtr_th
                    mtr_th.start()
                log_print(f"Started monitoring target: {t}" + (" (+ MTR)" if _MTR_AVAILABLE else ""))

            # stop removed
            for t in known_targets - new_targets:
                stop_flags[t]['stop'] = True
                threads.pop(t, None)
                stop_flags.pop(t, None)
                if t in _mtr_flags:
                    _mtr_flags[t]['stop'] = True
                    _mtr_threads.pop(t, None)
                    _mtr_flags.pop(t, None)
                log_print(f"Stopped monitoring target: {t}")

            known_targets = new_targets
        except KeyboardInterrupt:
            log_print("[SHUTDOWN] Agent stopping gracefully.")
            os._exit(0)
        except Exception as e:
            log_print(f"Polling error: {e}")
        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log_print("[SHUTDOWN] Agent stopping gracefully.")
            os._exit(0)

if __name__=="__main__":
    log_print("="*60)
    log_print("Mac Agent starting:")
    log_print(f"  AGENT_NAME: {AGENT_NAME}")
    log_print(f"  SERVER_URL: {SERVER_URL}")
    log_print(f"  SCRIPT_DIR: {SCRIPT_DIR}")
    log_print(f"  LOG_FILE: {LOG_FILE}")
    log_print(f"  POLL_INTERVAL: {POLL_INTERVAL} seconds")
    log_print(f"  Smart monitoring: Only monitors when OBS is running")
    log_print("="*60)

    log_print("Detecting network information...")
    detect_client_info()

    log_print("Detecting GPU...")
    _gpu_name = _detect_gpu_name()
    log_print(f"[GPU] Detected: {_gpu_name} (usage % not collected on macOS)")

    push_agent_version()

    log_print("Detecting OBS streaming data...")
    detect_obs_streaming_data()

    push_client_info()

    def refresh_client_info():
        while True:
            time.sleep(300)  # 5 minutes
            detect_client_info()
            detect_obs_streaming_data()
            push_client_info()

    refresh_thread = threading.Thread(target=refresh_client_info, daemon=True)
    refresh_thread.start()

    log_print("Starting real-time network speed monitoring...")
    speed_thread = threading.Thread(target=network_speed_loop, daemon=True)
    speed_thread.start()

    log_print("Starting real-time CPU and memory monitoring...")
    stats_thread = threading.Thread(target=system_stats_loop, daemon=True)
    stats_thread.start()

    log_print("Starting on-demand MTR demand poller...")
    mtr_demand_thread = threading.Thread(target=_poll_mtr_demand, daemon=True)
    mtr_demand_thread.start()

    log_print(f"Starting auto-update checker (current build={CLIENT_BUILD}, check interval={UPDATE_CHECK_INTERVAL}s)...")
    update_thread = threading.Thread(target=auto_update_loop, daemon=True)
    update_thread.start()

    cleanup_thread = threading.Thread(target=log_cleanup_loop, daemon=True)
    cleanup_thread.start()

    log_print("Starting target management loop...")
    try:
        manage_targets_loop()
    except KeyboardInterrupt:
        log_print("[SHUTDOWN] Agent stopping gracefully.")
        os._exit(0)
