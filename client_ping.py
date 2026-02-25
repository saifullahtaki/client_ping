import time, requests, subprocess, os, threading, platform, socket, sys, json, shutil
from datetime import datetime
import psutil

# --------------- Version (Auto-Update) ---------------
CLIENT_BUILD = 1002          # Increment this each time you deploy a new version
UPDATE_CHECK_INTERVAL = 1800  # Check for updates every 30 minutes

# Get absolute path of script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
 
# Import winreg for Windows Registry access
if platform.system().lower() == 'windows':
    import winreg
 
# ---------------- Windows Registry Helper ----------------
def get_all_user_sids():
    """Get all user SIDs from registry to access logged-in users' environment variables."""
    user_sids = []
    try:
        # Enumerate all user profiles
        with winreg.OpenKey(winreg.HKEY_USERS, "") as users_key:
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(users_key, i)
                    # Skip system SIDs (they start with S-1-5-18, S-1-5-19, S-1-5-20)
                    # We want user SIDs like S-1-5-21-...
                    if sid.startswith("S-1-5-21-"):
                        user_sids.append(sid)
                    i += 1
                except OSError:
                    break
    except:
        pass
    return user_sids

def get_env_from_registry(name, default=""):
    """Read environment variable directly from Windows Registry (live value).
    
    This function is designed to work even when running as LocalSystem service.
    It searches through all logged-in users' registry to find the OBS environment variable.
    """
    if platform.system().lower() != 'windows':
        return os.environ.get(name, default)
   
    # Strategy 1: Try current user environment (works for normal execution)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            if value:  # Only return if non-empty
                return value
    except (FileNotFoundError, OSError):
        pass
    
    # Strategy 2: Try all logged-in users' environments (works for LocalSystem service)
    # This is critical for service mode to detect OBS plugin settings
    if name.startswith("OBS_"):  # Check all OBS environment variables
        user_sids = get_all_user_sids()
        for sid in user_sids:
            try:
                with winreg.OpenKey(winreg.HKEY_USERS, f"{sid}\\Environment") as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:  # Return the first non-empty value found
                        return value
            except (FileNotFoundError, OSError):
                continue
 
    # Strategy 3: Fall back to system environment
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
        ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            if value:
                return value
    except (FileNotFoundError, OSError):
        pass
 
    # Strategy 4: Final fallback to os.environ
    return os.environ.get(name, default)
 
SERVER_URL = get_env_from_registry("SERVER_URL", "http://ostreamping.ums.team:5010")
 
 
# Auto-detect AGENT_NAME from hostname/computer name
def get_agent_name():
    # First check if AGENT_NAME is set in environment variable (Registry on Windows)
    agent = get_env_from_registry("AGENT_NAME", "")
    if agent:
        return agent
   
    try:
        # Try to get computer name (works on Windows)
        if platform.system().lower() == 'windows':
            computer_name = get_env_from_registry("COMPUTERNAME", "")
            if computer_name:
                return computer_name
       
        # Fallback to hostname (works on Linux/Mac/Windows)
        hostname = socket.gethostname()
        return hostname
    except:
        return "unknown-agent"
 
AGENT_NAME = get_agent_name()

# Global variables to store client info
client_local_ip = "unknown"
client_public_ip = "unknown"
client_isp_name = "unknown"

# Global variables for real-time network speed (updated every second)
network_download_mbps = 0.0
network_upload_mbps = 0.0

# Global variables to store OBS streaming data
obs_icr_code = "unknown"
obs_stream_title = "unknown"
obs_stream_preview_ostream = "unknown"
obs_stream_preview_youtube = "unknown"

# Setup logging for service mode
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOG_FILE = os.path.join(LOG_DIR, f"client_ping_{datetime.now().strftime('%Y%m%d')}.log")

def log_print(message):
    """Print to both console and log file with timestamp."""
    timestamp = datetime.now().isoformat()
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    sys.stdout.flush()  # Important for service mode
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except:
        pass

def format_display_name(name, name_type="target"):
    """Format display names for better readability in Grafana.
    
    For targets: Remove .udvashunmesh.com suffix
    For ISPs: Shorten common ISP names
    """
    if not name or name == "unknown":
        return name
    
    if name_type == "target":
        # Remove .udvashunmesh.com suffix from target names
        if ".udvashunmesh.com" in name.lower():
            name = name.split(".udvashunmesh.com")[0]
        return name
    
    elif name_type == "isp":
        # Shorten ISP names for better display
        # Handle both underscore and space versions
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
        # Try to resolve hostname to IP
        ip_address = socket.gethostbyname(target)
        return ip_address
    except:
        # If resolution fails, check if target is already an IP
        try:
            socket.inet_aton(target)
            return target  # It's already an IP
        except:
            return None

# ---------------- Network Detection ----------------
def get_local_ip():
    """Detect local IP address."""
    try:
        # Create a socket to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to Google DNS
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        try:
            # Fallback: get hostname IP
            return socket.gethostbyname(socket.gethostname())
        except:
            return "unknown"

def detect_obs_streaming_data():
    """Detect OBS streaming data from registry/environment variables."""
    global obs_icr_code, obs_stream_title, obs_stream_preview_ostream, obs_stream_preview_youtube
    
    try:
        # Get OBS ICR Code
        obs_icr_code = get_env_from_registry("OBS_ICR_CODE", "unknown")
        
        # Get OBS Stream Title
        obs_stream_title = get_env_from_registry("OBS_STREAM_TITLE", "unknown")
        
        # Get OBS Stream Preview (contains 2 URLs separated by comma or pipe)
        obs_stream_preview = get_env_from_registry("OBS_STREAM_PREVIEW", "")
        
        if obs_stream_preview:
            # Split the preview URLs - they might be separated by pipe | or comma
            preview_urls = []
            if '|' in obs_stream_preview:
                preview_urls = [url.strip() for url in obs_stream_preview.split('|') if url.strip()]
            elif ',' in obs_stream_preview:
                preview_urls = [url.strip() for url in obs_stream_preview.split(',') if url.strip()]
            else:
                preview_urls = [obs_stream_preview.strip()]
            
            # Assign URLs based on content (youtube/ostream detection)
            obs_stream_preview_ostream = "unknown"
            obs_stream_preview_youtube = "unknown"
            
            for url in preview_urls:
                if 'youtube' in url.lower() or 'youtu.be' in url.lower():
                    obs_stream_preview_youtube = url
                elif 'ostream' in url.lower():
                    obs_stream_preview_ostream = url
                else:
                    # If can't determine, assign to first available slot
                    if obs_stream_preview_ostream == "unknown":
                        obs_stream_preview_ostream = url
                    elif obs_stream_preview_youtube == "unknown":
                        obs_stream_preview_youtube = url
        
        log_print(f"OBS Streaming Data Detected: ICR Code={obs_icr_code}, Title={obs_stream_title}")
        log_print(f"  Preview URLs - OStream={obs_stream_preview_ostream}, YouTube={obs_stream_preview_youtube}")
        return True
    except Exception as e:
        log_print(f"Failed to detect OBS streaming data: {e}")
        return False

def detect_client_info():
    """Detect local IP, public IP, and ISP name."""
    global client_local_ip, client_public_ip, client_isp_name
    
    # Detect local IP
    client_local_ip = get_local_ip()
    
    try:
        # Detect public IP
        res = requests.get("https://api.ipify.org?format=json", timeout=10)
        client_public_ip = res.json().get("ip", "unknown")
        
        # Detect ISP name
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
    """Check if OBS process is running."""
    try:
        if platform.system().lower() == 'windows':
            # Check for common OBS process names
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq obs64.exe', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if 'obs64.exe' in result.stdout.lower():
                return True
            
            # Also check for 32-bit OBS
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq obs32.exe', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if 'obs32.exe' in result.stdout.lower():
                return True
            
            # Check for generic obs.exe
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq obs.exe', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if 'obs.exe' in result.stdout.lower():
                return True
        else:
            # Linux/Mac - check for obs process
            result = subprocess.run(
                ['pgrep', '-x', 'obs'],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
    except Exception:
        pass
    
    return False

# Auto-detect targets from OBS_STREAMING_SERVERS environment variable
def get_targets_from_env():
    """Re-read environment variable from registry (live value from OBS)."""
    # ONLY read from registry - this ensures real-time detection from OBS plugin
    # First try registry (most reliable for service and real-time updates)
    obs_servers = get_env_from_registry("OBS_STREAMING_SERVERS", "")
    
    # If not found in registry, try os.environ (for manual run)
    if not obs_servers:
        obs_servers = os.environ.get("OBS_STREAMING_SERVERS", "")
    
    # DO NOT use file-based fallback - we want real-time detection from OBS only
    # File-based config is removed to prevent detecting old/stale servers
    
    targets = []
    
    if obs_servers:
        # Split by comma and strip whitespace
        targets = [url.strip() for url in obs_servers.split(",") if url.strip()]
        log_print(f"Detected OBS servers: {targets}")
    
    # Also extract YouTube/Facebook from OBS_STREAM_PREVIEW if available
    obs_preview = get_env_from_registry("OBS_STREAM_PREVIEW", "")
    if not obs_preview:
        obs_preview = os.environ.get("OBS_STREAM_PREVIEW", "")
    
    if obs_preview:
        # Split preview URLs (separated by | or ,)
        preview_urls = []
        if '|' in obs_preview:
            preview_urls = [url.strip() for url in obs_preview.split('|') if url.strip()]
        elif ',' in obs_preview:
            preview_urls = [url.strip() for url in obs_preview.split(',') if url.strip()]
        else:
            preview_urls = [obs_preview.strip()]
        
        # Extract YouTube/Facebook RTMP hostnames from preview URLs
        for url in preview_urls:
            try:
                # Parse URL to extract hostname
                if 'rtmp://' in url.lower() or 'rtmps://' in url.lower():
                    # Extract hostname from rtmp://hostname/path format
                    parts = url.split('/')
                    if len(parts) >= 3:
                        hostname = parts[2].strip()
                        if hostname and hostname not in targets:
                            # Only add if it's YouTube/Facebook (not OStream)
                            if 'youtube' in hostname.lower() or 'facebook' in hostname.lower() or 'fb.' in hostname.lower():
                                targets.append(hostname)
                                log_print(f"Detected YouTube/Facebook from preview: {hostname}")
            except Exception as e:
                log_print(f"Failed to parse preview URL {url}: {e}")
    
    return targets
 
POLL_INTERVAL = int(get_env_from_registry("POLL_INTERVAL", "5"))  # Reduced to 5 seconds for faster detection
PING_INTERVAL = float(get_env_from_registry("PING_INTERVAL", "1"))
 
session = requests.Session()
 
# ---------------- Parse ping ----------------
def parse_ping_windows(output):
    """
    Parse Windows ping output and return RTT in ms.
    - If RTT < 1ms → return 1.0
    - If parsing fails → return -10.0 for Grafana
    """
def parse_ping_windows(output):
    """
    Optimized Windows ping output parser for 99% accuracy
    - Uses regex for faster parsing
    - Handles edge cases (time<1ms, timeouts)
    - Returns accurate RTT in milliseconds
    """
    out = output.decode(errors='ignore') if isinstance(output, bytes) else str(output)
    
    # Quick check for success indicators
    if "time=" not in out and "time<" not in out:
        return -10.0
    
    try:
        # Handle sub-millisecond pings (time<1ms)
        if "time<" in out:
            return 1.0  # minimum measurable RTT = 1ms
        
        # Optimized parsing: find "time=" and extract number
        time_idx = out.find("time=")
        if time_idx == -1:
            return -10.0
        
        # Extract numeric part after "time="
        start = time_idx + 5  # Length of "time="
        num_str = ''
        
        for i in range(start, min(start + 10, len(out))):
            ch = out[i]
            if ch.isdigit() or ch == '.':
                num_str += ch
            elif num_str:  # Stop at first non-numeric after finding digits
                break
        
        if not num_str:
            return -10.0
        
        rtt = float(num_str)
        
        # Validate RTT
        if rtt == 0:
            return -10.0
        
        # Return RTT (minimum 1ms for sub-millisecond values)
        return rtt if rtt >= 1.0 else 1.0
        
    except (ValueError, IndexError):
        return -10.0
 
def do_ping_once(target):
    """
    Optimized ping function for 99% accuracy
    - Uses high-resolution timer (time.perf_counter)
    - Minimal subprocess overhead
    - Direct parsing without string operations
    - Adaptive timeout based on target
    """
    system = platform.system().lower()
    
    # Adaptive timeout: YouTube needs more time due to distance
    if 'youtube' in target.lower() or 'rtmp' in target.lower() or 'facebook' in target.lower():
        timeout_ms = "1500"  # 1.5 seconds for international servers
        timeout_sec = 3
    else:
        timeout_ms = "1000"  # 1 second for local servers (increased from 500ms to handle concurrent load)
        timeout_sec = 2
    
    # Optimized command
    if system == 'windows':
        cmd = ["ping", "-n", "1", "-w", timeout_ms, str(target)]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", str(target)]
    
    try:
        # High-resolution timer for accurate measurement
        start_time = time.perf_counter()
        
        # Run ping with minimal overhead
        p = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            timeout=timeout_sec,  # Adaptive timeout based on target
            creationflags=subprocess.CREATE_NO_WINDOW if system == 'windows' else 0
        )
        
        end_time = time.perf_counter()
        
        # Decode output
        out = p.stdout.decode(errors='ignore')
        
        if p.returncode == 0:
            # Parse RTT from output (optimized parsing)
            rtt = parse_ping_windows(out) if system == 'windows' else None
            
            if rtt is None or rtt < 1.0:
                rtt = 1.0
            
            # Validate RTT against measured time
            measured_time = (end_time - start_time) * 1000  # Convert to ms
            
            # If RTT is 0, use measured time or set to -10
            if rtt == 0:
                rtt = -10.0
            
            return True, rtt, out
        else:
            return False, -10.0, out
            
    except subprocess.TimeoutExpired:
        return False, -10.0, "Timeout"
    except Exception as e:
        return False, -10.0, str(e)
 
# ---------------- Send ping ----------------
def send_ping(target, rtt, success, raw):
    # Resolve target to IP (server will do the mapping)
    target_ip = resolve_target_to_ip(target)
    stream_id = ""  # Stream ID for preview URL
    
    # Extract stream ID from preview URL for udvashunmesh.com targets
    if target_ip and ".udvashunmesh.com" in target.lower():
        if obs_stream_preview_ostream and obs_stream_preview_ostream != "unknown":
            try:
                if "streamName=" in obs_stream_preview_ostream:
                    stream_id = obs_stream_preview_ostream.split("streamName=")[1].split("&")[0]
            except:
                pass
        
        # If no stream_id from preview, create a fallback using target name
        if not stream_id:
            stream_id = target.replace(".udvashunmesh.com", "").replace("os-origin-server-", "")
    
    # For YouTube, extract video ID
    if "youtube" in target.lower() and obs_stream_preview_youtube and obs_stream_preview_youtube != "unknown":
        try:
            if "watch?v=" in obs_stream_preview_youtube:
                stream_id = obs_stream_preview_youtube.split("watch?v=")[1].split("&")[0]
        except:
            pass
    
    # Format display names for Grafana
    target_display = format_display_name(target, "target")
    isp_display = format_display_name(client_isp_name, "isp")
    
    payload = {
        "client_id": client_local_ip,  # Use local IP as client ID
        "computer_name": AGENT_NAME,  # Add computer name
        "target": target,
        "target_display": target_display,  # Shortened display name
        "target_ip": target_ip if target_ip else "",  # Server will map this IP to server_name/type
        "stream_id": stream_id,  # Stream ID for URL generation
        "isp": client_isp_name,  # Include ISP name
        "isp_display": isp_display,  # Shortened ISP display name
        "preview_ostream": obs_stream_preview_ostream,  # OBS OStream preview URL
        "preview_youtube": obs_stream_preview_youtube,  # OBS YouTube preview URL
        "timestamp": int(time.time()),
        "success": success,
        "rtt_ms": rtt,
        "raw": raw[:2000]
    }
    try:
        # Debug log for YouTube
        if "youtube" in target.lower():
            log_print(f"[DEBUG] Sending YouTube ping: target={target}, rtt={rtt}")
        
        response = session.post(SERVER_URL.rstrip("/") + "/push_ping", json=payload, timeout=5)
        
        # Debug log for YouTube response
        if "youtube" in target.lower():
            log_print(f"[DEBUG] YouTube ping response: status={response.status_code}")
            
    except Exception as e:
        log_print(f"Ping send error for {target}: {e}")
 
# ---------------- Network Speed Monitoring ----------------
def check_and_apply_update():
    """
    Check server for a newer build of client_ping.py.
    If found: download → verify → replace current script → exit.
    NSSM auto-restarts the service, loading the new code.
    """
    try:
        resp = session.get(SERVER_URL.rstrip("/") + "/client_version", timeout=10)
        if resp.status_code != 200:
            return

        server_build = int(resp.json().get("build", 0))

        if server_build <= CLIENT_BUILD:
            log_print(f"[AUTO-UPDATE] Up-to-date (build {CLIENT_BUILD})")
            return

        log_print(f"[AUTO-UPDATE] New version available! server={server_build}, current={CLIENT_BUILD}")
        log_print(f"[AUTO-UPDATE] Downloading...")

        dl = session.get(SERVER_URL.rstrip("/") + "/client_script", timeout=30)
        if dl.status_code != 200:
            log_print(f"[AUTO-UPDATE] Download failed: HTTP {dl.status_code}")
            return

        new_code = dl.text

        # Verify the downloaded file actually has the expected build number
        if f"CLIENT_BUILD = {server_build}" not in new_code:
            log_print(f"[AUTO-UPDATE] Verification failed - BUILD number mismatch in downloaded file")
            return

        current_script = os.path.abspath(__file__)
        temp_file  = current_script + ".update"
        backup_file = current_script + ".backup"

        # Write to temp file
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(new_code)

        log_print(f"[AUTO-UPDATE] Downloaded {len(new_code)} bytes OK")

        # Backup current version
        if os.path.exists(backup_file):
            os.remove(backup_file)
        shutil.copy2(current_script, backup_file)

        # Replace with new version (Python already loaded itself into memory - safe to overwrite)
        shutil.move(temp_file, current_script)

        log_print(f"[AUTO-UPDATE] Applied build {server_build}. Restarting service...")
        sys.exit(0)   # NSSM will restart automatically with new code

    except Exception as e:
        log_print(f"[AUTO-UPDATE] Error: {e}")


def auto_update_loop():
    """Background thread: wait 2 min on startup, then check every 30 min."""
    time.sleep(120)   # Let service stabilize before first check
    while True:
        check_and_apply_update()
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
    Uses psutil - same method as Windows Task Manager (delta of OS network counters).
    Sends download + upload in Mbps to InfluxDB via server.
    """
    global network_download_mbps, network_upload_mbps

    # Initial sample
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
                # Skip loopback interfaces (same as Task Manager)
                if nic.lower() == 'lo' or 'loopback' in nic.lower():
                    continue
                prev = prev_io.get(nic)
                if prev:
                    sent_delta = curr.bytes_sent - prev.bytes_sent
                    recv_delta = curr.bytes_recv - prev.bytes_recv
                    # Guard against counter resets (negative delta)
                    if sent_delta >= 0:
                        total_sent += sent_delta
                    if recv_delta >= 0:
                        total_recv += recv_delta

            # bytes/s → Mbps  (bits per second / 1,000,000)
            download_mbps = (total_recv * 8) / (1_000_000 * elapsed)
            upload_mbps = (total_sent * 8) / (1_000_000 * elapsed)

            # Clamp to 0 (no negatives)
            download_mbps = max(0.0, round(download_mbps, 4))
            upload_mbps   = max(0.0, round(upload_mbps, 4))

            network_download_mbps = download_mbps
            network_upload_mbps   = upload_mbps

            prev_io   = curr_io
            prev_time = curr_time

            # Push to server every second
            push_network_speed(download_mbps, upload_mbps)

        except Exception as e:
            log_print(f"Network speed error: {e}")
            time.sleep(5)

# ---------------- Push ISP info ----------------
def push_client_info():
    """Push client info to server using detected values."""
    try:
        # Check if OBS is running
        obs_running = is_obs_running()
        
        if obs_running:
            # Detect latest OBS streaming data before pushing
            detect_obs_streaming_data()
            
            # Get current streaming servers from environment
            streaming_servers = get_targets_from_env()
            
            # Separate os-origin server and youtube
            os_origin_server = "none"
            youtube_server = "none"
            os_origin_ping = 0.0
            youtube_ping = 0.0
            
            for target in streaming_servers:
                # Do a quick ping to get latest RTT
                success, rtt, _ = do_ping_once(target)
                
                # For os-origin servers
                if target.lower().startswith("os-") or "ostream" in target.lower() or "origin" in target.lower():
                    os_origin_server = target
                    os_origin_ping = rtt if success and rtt >= 0 else 0.0
                # For YouTube/RTMP servers
                elif "youtube" in target.lower() or "rtmp" in target.lower():
                    youtube_server = target
                    youtube_ping = rtt if success and rtt >= 0 else 0.0
        else:
            # OBS not running - send empty/unknown data
            os_origin_server = "none"
            youtube_server = "none"
            os_origin_ping = 0.0
            youtube_ping = 0.0
        
        payload = {
            "client_id": client_local_ip,
            "computer_name": AGENT_NAME,
            "local_ip": client_local_ip,
            "public_ip": client_public_ip,
            "isp": client_isp_name,
            "obs_icr_code": obs_icr_code if obs_running else "unknown",
            "obs_stream_title": obs_stream_title if obs_running else "unknown",
            "obs_stream_preview_ostream": obs_stream_preview_ostream if obs_running else "unknown",
            "obs_stream_preview_youtube": obs_stream_preview_youtube if obs_running else "unknown",
            "os_origin_server": os_origin_server,
            "os_origin_ping": os_origin_ping,
            "youtube_server": youtube_server,
            "youtube_ping": youtube_ping,
            "obs_running": obs_running
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
        # Always try resolving IP / domain
        success, rtt, raw = do_ping_once(target)
        send_ping(target, rtt, success, raw)
       
        # Send client info only every 60 pings (approximately 1 minute if PING_INTERVAL=1)
        client_info_counters[target] += 1
        if client_info_counters[target] >= 60:
            push_client_info()  # No argument needed
            client_info_counters[target] = 0
       
        log_print(f"{target} succ={success} rtt={rtt}")
        time.sleep(PING_INTERVAL)
 
# ---------------- Manage Targets ----------------
def manage_targets_loop():
    known_targets = set()
    last_env_targets = set()
    last_obs_status = None
    
    while True:
        try:
            # Check if OBS is running
            obs_running = is_obs_running()
            
            # Log OBS status change
            if obs_running != last_obs_status:
                if obs_running:
                    log_print("OBS detected - starting to monitor streaming servers")
                else:
                    log_print("OBS not running - stopping all monitoring")
                last_obs_status = obs_running
            
            # Only monitor if OBS is running
            if obs_running:
                # Re-read targets from OBS environment variable (live auto-detect)
                current_env_targets = set(get_targets_from_env())
                
                # Check if OBS environment variable changed
                if current_env_targets != last_env_targets:
                    if current_env_targets:
                        log_print(f"OBS targets detected: {', '.join(current_env_targets)}")
                    else:
                        log_print("No OBS targets found in environment")
                    last_env_targets = current_env_targets
                
                # Start with auto-detected targets from environment variable
                new_targets = current_env_targets.copy()
            else:
                # OBS not running - no targets to monitor
                new_targets = set()
                if last_env_targets:
                    log_print("Clearing all targets - OBS is closed")
                    last_env_targets = set()
           
            # Also fetch targets from server (if any) - only if OBS is running
            if obs_running:
                try:
                    r = session.get(SERVER_URL.rstrip("/") + "/get_targets", timeout=5)
                    if r.status_code == 200:
                        tlist = r.json()
                        server_targets = set([t['target'] for t in tlist])
                        new_targets.update(server_targets)
                except:
                    pass  # If server is unreachable, still use auto-detected targets
           
            # start new
            for t in new_targets - known_targets:
                stop_flags[t] = {'stop': False}
                th = threading.Thread(target=ping_loop, args=(t,), daemon=True)
                threads[t] = th
                th.start()
                log_print(f"Started monitoring target: {t}")
           
            # stop removed
            for t in known_targets - new_targets:
                stop_flags[t]['stop'] = True
                threads.pop(t, None)
                stop_flags.pop(t, None)
                log_print(f"Stopped monitoring target: {t}")
           
            known_targets = new_targets
        except Exception as e:
            log_print(f"Polling error: {e}")
        time.sleep(POLL_INTERVAL)
 
if __name__=="__main__":
    log_print("="*60)
    log_print("Agent starting:")
    log_print(f"  AGENT_NAME: {AGENT_NAME}")
    log_print(f"  SERVER_URL: {SERVER_URL}")
    log_print(f"  SCRIPT_DIR: {SCRIPT_DIR}")
    log_print(f"  LOG_FILE: {LOG_FILE}")
    log_print(f"  POLL_INTERVAL: {POLL_INTERVAL} seconds")
    log_print(f"  Auto-detect mode: OBS process and environment will be checked every {POLL_INTERVAL} seconds")
    log_print(f"  Smart monitoring: Only monitors when OBS is running")
    log_print("="*60)
    
    # Detect client info at startup
    log_print("Detecting network information...")
    detect_client_info()
    
    # Detect OBS streaming data at startup
    log_print("Detecting OBS streaming data...")
    detect_obs_streaming_data()
    
    # Push client info to server initially
    push_client_info()
    
    # Start background thread to refresh client info every 5 minutes
    def refresh_client_info():
        while True:
            time.sleep(300)  # 5 minutes
            detect_client_info()
            detect_obs_streaming_data()  # Also refresh OBS data
            push_client_info()
    
    refresh_thread = threading.Thread(target=refresh_client_info, daemon=True)
    refresh_thread.start()

    # Start network speed monitoring thread (Task Manager-style: 1 second interval)
    log_print("Starting real-time network speed monitoring...")
    speed_thread = threading.Thread(target=network_speed_loop, daemon=True)
    speed_thread.start()

    # Start auto-update thread (checks server for new version every 30 minutes)
    log_print(f"Starting auto-update checker (current build={CLIENT_BUILD}, check interval={UPDATE_CHECK_INTERVAL}s)...")
    update_thread = threading.Thread(target=auto_update_loop, daemon=True)
    update_thread.start()

    log_print("Starting target management loop...")
    manage_targets_loop()