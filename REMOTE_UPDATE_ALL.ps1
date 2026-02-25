# ============================================================
# REMOTE_UPDATE_ALL.ps1
# Remotely updates client_ping.py on all studio PCs and
# restarts the StudioPingService - NO physical visit needed.
#
# Run from: MH-NETWORK-MONI (or any admin PC)
# Run as:   Administrator
# ============================================================

# Self-bypass: re-launch with ExecutionPolicy Bypass if needed
if ($MyInvocation.ScriptName -ne "" -and
    [System.Security.Principal.WindowsPrincipal]::new(
        [System.Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator) -eq $false) {
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
    exit
}

if ((Get-ExecutionPolicy -Scope Process) -eq "Restricted") {
    Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
}

$LocalScript  = "C:\agent\client_ping.py"   # Latest file on THIS PC
$RemoteDest   = "c$\agent\client_ping.py"    # Admin share path on target PCs
$ServiceName  = "StudioPingService"

# ============================================================
# LIST OF ALL STUDIO PCs  (add/remove as needed)
# Format: "IP_or_Hostname"
# ============================================================
$StudioPCs = @(
    # Online PCs found on network (192.168.40.x)
    # Remove any non-studio PCs (routers, printers, etc.)
    "192.168.40.200",
    "192.168.40.109",
    "192.168.40.125"
    # .1  = Router (skipped)
    # .18 = This PC MH-NETWORK-MONI (skipped)
    # .26 = Server/app.py (skipped)
)

# ============================================================
# Read current BUILD number from local file
# ============================================================
$buildMatch = Select-String -Path $LocalScript -Pattern "CLIENT_BUILD\s*=\s*(\d+)"
$localBuild = if ($buildMatch) { $buildMatch.Matches[0].Groups[1].Value } else { "unknown" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Remote Update - Studio PCs" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Source file : $LocalScript" -ForegroundColor White
Write-Host "  Build       : $localBuild" -ForegroundColor Yellow
Write-Host "  Target PCs  : $($StudioPCs.Count)" -ForegroundColor White
Write-Host ""

if (-not (Test-Path $LocalScript)) {
    Write-Host "[ERROR] Source file not found: $LocalScript" -ForegroundColor Red
    exit 1
}

# ============================================================
# Results tracking
# ============================================================
$results = @()

foreach ($pc in $StudioPCs) {

    $status = [PSCustomObject]@{
        PC      = $pc
        Ping    = $false
        Copied  = $false
        Service = $false
        Note    = ""
    }

    Write-Host "------------------------------------------------------------"
    Write-Host "  PC: $pc" -ForegroundColor White

    # --- Step 1: Ping check ---
    $pingOK = Test-Connection -ComputerName $pc -Count 1 -Quiet -ErrorAction SilentlyContinue
    if (-not $pingOK) {
        Write-Host "  [SKIP] Unreachable (offline or wrong IP)" -ForegroundColor DarkGray
        $status.Note = "Offline"
        $results += $status
        continue
    }
    $status.Ping = $true
    Write-Host "  [OK] Reachable" -ForegroundColor Green

    # --- Step 2: Copy file via Admin Share ---
    $dest = "\\$pc\$RemoteDest"
    try {
        Copy-Item -Path $LocalScript -Destination $dest -Force -ErrorAction Stop
        $status.Copied = $true
        Write-Host "  [OK] File copied to $dest" -ForegroundColor Green
    } catch {
        $errMsg = $_.Exception.Message
        Write-Host "  [FAIL] Copy failed: $errMsg" -ForegroundColor Red
        $status.Note = "Copy failed: $errMsg"
        $results += $status
        continue
    }

    # --- Step 3: Restart service remotely ---
    try {
        $svc = Get-Service -ComputerName $pc -Name $ServiceName -ErrorAction Stop

        # Stop
        if ($svc.Status -ne "Stopped") {
            Stop-Service -InputObject $svc -Force -ErrorAction Stop
            Start-Sleep -Seconds 2
        }

        # Start
        Start-Service -InputObject $svc -ErrorAction Stop
        Start-Sleep -Seconds 2

        # Verify
        $svc.Refresh()
        if ($svc.Status -eq "Running") {
            $status.Service = $true
            Write-Host "  [OK] Service restarted - Running" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] Service status: $($svc.Status)" -ForegroundColor Yellow
            $status.Note = "Service status: $($svc.Status)"
        }
    } catch {
        $errMsg = $_.Exception.Message
        Write-Host "  [FAIL] Service restart failed: $errMsg" -ForegroundColor Red
        $status.Note = "Service restart failed: $errMsg"
    }

    $results += $status
}

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SUMMARY (Build $localBuild deployed)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$success = ($results | Where-Object { $_.Copied -and $_.Service }).Count
$copied  = ($results | Where-Object { $_.Copied }).Count
$offline = ($results | Where-Object { -not $_.Ping }).Count
$failed  = ($results | Where-Object { $_.Ping -and -not $_.Copied }).Count

Write-Host ("  {0,-20} {1,-8} {2,-8} {3}" -f "PC", "Copied", "Service", "Note") -ForegroundColor Cyan
Write-Host ("  {0,-20} {1,-8} {2,-8} {3}" -f "--", "------", "-------", "----") -ForegroundColor DarkGray

foreach ($r in $results) {
    $copiedIcon  = if ($r.Copied)  { "[OK]" } else { "[--]" }
    $serviceIcon = if ($r.Service) { "[OK]" } else { "[--]" }
    $color = if ($r.Copied -and $r.Service) { "Green" } elseif (-not $r.Ping) { "DarkGray" } else { "Yellow" }
    Write-Host ("  {0,-20} {1,-8} {2,-8} {3}" -f $r.PC, $copiedIcon, $serviceIcon, $r.Note) -ForegroundColor $color
}

Write-Host ""
Write-Host "  Total   : $($StudioPCs.Count) PCs" -ForegroundColor White
Write-Host "  Updated : $success PCs (file copied + service running)" -ForegroundColor Green
Write-Host "  Offline : $offline PCs (unreachable)" -ForegroundColor DarkGray
Write-Host "  Failed  : $failed PCs (reachable but copy failed - check admin share)" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host ""
Write-Host "TIP: If 'Copy failed' - ensure Admin Share (c$) is accessible" -ForegroundColor Yellow
Write-Host "     and you are running this script as Administrator." -ForegroundColor Yellow
Write-Host ""

Read-Host "Press Enter to exit"
