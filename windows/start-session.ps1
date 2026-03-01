# @raycast.schemaVersion 1
# @raycast.title Start Grafana Export Session
# @raycast.mode fullOutput
# @raycast.packageName Grafana
# @raycast.icon 🖨️

# Dependencies:
#   uv:      powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
#   poppler: winget install oschwartz10612.Poppler   (provides pdftoppm for PDF→PNG conversion)

$dir     = "$env:USERPROFILE\.grafana-png-exporter"
$pidFile = "$dir\session.pid"
$script  = "$env:USERPROFILE\raycast\scripts\grafana-png-export.py"

if (Test-Path $pidFile)
{
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)
    {
        Add-Type -AssemblyName System.Windows.Forms
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon    = [System.Drawing.SystemIcons]::Information
        $n.Visible = $true
        $n.ShowBalloonTip(5000, "Grafana Exporter", "A session is already running", 1)
        Start-Sleep -Milliseconds 500
        $n.Dispose()
        exit 0
    }
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null

# Write a launcher script that handles its own I/O redirection.
# This avoids the -WindowStyle Hidden + -RedirectStandardOutput incompatibility.
$launcher = "$dir\launcher.ps1"
@"
& '$env:USERPROFILE\.local\bin\uv.exe' run '$script' *> '$dir\session.log'
"@ | Set-Content $launcher

Start-Process powershell `
    -WindowStyle Hidden `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher
