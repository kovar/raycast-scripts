# @raycast.schemaVersion 1
# @raycast.title Stop Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon ⏹️

$dir     = "$env:USERPROFILE\.grafana-png-exporter"
$pidFile = "$dir\session.pid"
$trigger = "$dir\stop.trigger"

if (-not (Test-Path $pidFile))
{ exit 0 
}

$savedPid = [int](Get-Content $pidFile -Raw).Trim()
if (-not (Get-Process -Id $savedPid -ErrorAction SilentlyContinue))
{ exit 0 
}

New-Item -ItemType File -Force -Path $trigger | Out-Null
