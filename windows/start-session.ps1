# @raycast.schemaVersion 1
# @raycast.title Start Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 🖨️
# @raycast.argument1 { "type": "dropdown", "placeholder": "Export format", "data": [{"title": "16:9 - 1920 x 1080 page, 6000 x 3375 PNG (default)", "value": "16:9"}, {"title": "A4 landscape - 1697 x 1200 page, 5303 x 3750 PNG", "value": "a4-landscape"}, {"title": "A4 portrait - 849 x 1200 page, 2653 x 3750 PNG", "value": "a4"}, {"title": "16:10 - 1920 x 1200 page, 6000 x 3750 PNG", "value": "16:10"}, {"title": "4:3 - 1600 x 1200 page, 5000 x 3750 PNG", "value": "4:3"}, {"title": "Custom - type page size in px below (W x H)", "value": "custom"}] }
# @raycast.argument2 { "type": "text", "placeholder": "Custom page size in px, e.g. 1400x990", "optional": true }

# Dependencies:
#   uv:      powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
#   poppler: winget install oschwartz10612.Poppler   (provides pdftoppm for PDF→PNG conversion)

param(
    [string]$Format = "16:9",
    [string]$CustomSize = ""
)

function Show-Toast([string]$message)
{
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon    = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(5000, "Grafana Exporter", $message, 1)
    Start-Sleep -Milliseconds 500
    $n.Dispose()
}

$dir     = "$env:USERPROFILE\.grafana-png-exporter"
$pidFile = "$dir\session.pid"
$script  = "$env:USERPROFILE\raycast\scripts\grafana-png-export.py"

if (Test-Path $pidFile)
{
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)
    {
        Show-Toast "A session is already running"
        exit 0
    }
}

if ($Format -eq "") { $Format = "16:9" }
if ($Format -eq "custom")
{
    $Format = $CustomSize -replace '\s', ''
    if ($Format -notmatch '^\d+[xX]\d+$')
    {
        Show-Toast "Custom size required - enter page size in px, e.g. 1400x990"
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null

# Write a launcher script that handles its own I/O redirection.
# This avoids the -WindowStyle Hidden + -RedirectStandardOutput incompatibility.
$launcher = "$dir\launcher.ps1"
@"
& '$env:USERPROFILE\.local\bin\uv.exe' run '$script' --format '$Format' *> '$dir\session.log'
"@ | Set-Content $launcher

Start-Process powershell `
    -WindowStyle Hidden `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher
