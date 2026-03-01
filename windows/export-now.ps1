# @raycast.schemaVersion 1
# @raycast.title Export Grafana PNG Now
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 📄

$dir     = "$env:USERPROFILE\.grafana-png-exporter"
$pidFile = "$dir\session.pid"
$trigger = "$dir\export.trigger"

$running = (Test-Path $pidFile) -and `
           (Get-Process -Id ([int](Get-Content $pidFile -Raw).Trim()) -ErrorAction SilentlyContinue)

if (-not $running) {
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon    = [System.Drawing.SystemIcons]::Warning
    $n.Visible = $true
    $n.ShowBalloonTip(5000, "Grafana Exporter", "No active session - run 'Start Grafana Export Session' first", 2)
    Start-Sleep -Milliseconds 500
    $n.Dispose()
    exit 1
}

New-Item -ItemType File -Force -Path $trigger | Out-Null
