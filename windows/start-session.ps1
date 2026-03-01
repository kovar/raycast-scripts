# @raycast.schemaVersion 1
# @raycast.title Start Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 🖨️

# Dependencies:
#   uv:      powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
#   poppler: winget install oschwartz10612.Poppler   (provides pdftoppm for PDF→PNG conversion)

$dir     = "$env:USERPROFILE\.grafana-png-exporter"
$pidFile = "$dir\session.pid"
$script  = "$env:USERPROFILE\raycast\scripts\grafana-png-export.py"

if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue) {
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
Start-Process -NoNewWindow `
    -FilePath "$env:USERPROFILE\.local\bin\uv.exe" `
    -ArgumentList "run", $script `
    -RedirectStandardOutput "$dir\session.log" `
    -RedirectStandardError  "$dir\session-err.log"
