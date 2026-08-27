# @raycast.schemaVersion 1
# @raycast.title Compress iOS Scan
# @raycast.mode silent
# @raycast.icon 📉
# @raycast.description Compress the PDF(s) currently copied in Explorer (Ctrl+C them first); saves alongside as *_compressed.pdf
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar
# @raycast.argument1 { "type": "dropdown", "placeholder": "Quality", "data": [
#   { "title": "Small - 64 colors, 50% res (default, ~90% smaller)", "value": "small" },
#   { "title": "Lossless - no quality loss (~15-20% smaller)", "value": "lossless" },
#   { "title": "HQ - 256 colors, 100% res (~55-70% smaller)", "value": "hq" },
#   { "title": "Balanced - 64 colors, 75% res (~80% smaller)", "value": "balanced" },
#   { "title": "Tiny - 64 colors, 33% res (~96% smaller, aggressive)", "value": "tiny" }
# ] }
# @raycast.argument2 { "type": "text", "placeholder": "Real size in cm, e.g. 8.5x5.3 (optional, recommended for lossy tiers)", "optional": true }

# No Windows equivalent of macOS's "ask Finder for the current selection" exists
# here, so this script reads the clipboard's file list instead:
#   -> select the PDF(s) in File Explorer, press Ctrl+C, THEN run this command.
#
# Dependencies:
#   uv:     powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
#   oxipng (optional but recommended - better lossless recompression):
#           winget install Shssoichiro.Oxipng

param(
    [string]$Quality = "small",
    [string]$Size = ""
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-Toast([string]$title, [string]$message, [string]$level = "warning") {
    $icon = if ($level -eq "info") { [System.Drawing.SystemIcons]::Information } else { [System.Drawing.SystemIcons]::Warning }
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = $icon
    $n.Visible = $true
    $n.ShowBalloonTip(5000, $title, $message, 2)
    Start-Sleep -Milliseconds 500
    $n.Dispose()
}

$files = [System.Windows.Forms.Clipboard]::GetFileDropList()

$pdfFiles = @($files | Where-Object { $_ -like "*.pdf" -or $_ -like "*.PDF" })

if ($pdfFiles.Count -lt 1) {
    Show-Toast "Compress iOS Scan" "No PDF(s) on clipboard - select file(s) in Explorer and press Ctrl+C first"
    exit 1
}

$scriptDir = Split-Path -Parent $PSScriptRoot
$coreScript = Join-Path $scriptDir "compress-ios-scan.py"

$uv = "$env:USERPROFILE\.local\bin\uv.exe"
if (-not (Test-Path $uv)) { $uv = "uv" }

$scriptArgs = @($coreScript) + $pdfFiles + @("--quality", $Quality)
if ($Size -ne "") { $scriptArgs += @("--size", $Size) }

$output = & $uv run @scriptArgs 2>&1 | Out-String

if ($LASTEXITCODE -ne 0) {
    Show-Toast "Compress iOS Scan failed" ($output.Substring(0, [Math]::Min(200, $output.Length))) "warning"
    exit 1
}

$trimmed = $output.Trim()
Show-Toast "Compress iOS Scan" ($trimmed.Substring(0, [Math]::Min(200, $trimmed.Length))) "info"
