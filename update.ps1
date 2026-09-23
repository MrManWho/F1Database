# Paddock Legacy updater. Run through update.bat.
$ErrorActionPreference = "Stop"
$repoZip = "https://github.com/MrManWho/F1Database/archive/HEAD.zip"
$here = $PSScriptRoot

Write-Host "Paddock Legacy updater" -ForegroundColor Red
Write-Host ""

# Refuse to update while the tracker is running.
$running = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $running = $client.ConnectAsync("127.0.0.1", 8765).Wait(500)
    $client.Close()
} catch { $running = $false }
if ($running) {
    Write-Host "The tracker is still running. Close its black window first, then run update.bat again." -ForegroundColor Yellow
    exit 1
}

$zip = Join-Path $env:TEMP "f1tracker-update.zip"
$unpack = Join-Path $env:TEMP "f1tracker-update"
try {
    Write-Host "Downloading the latest version..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $repoZip -OutFile $zip -UseBasicParsing
    if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $unpack -Force
    $source = (Get-ChildItem $unpack -Directory | Select-Object -First 1).FullName

    $old = "unknown"
    $constants = Join-Path $here "f1tracker\constants.py"
    if (Test-Path $constants) {
        $m = Select-String -Path $constants -Pattern 'APP_VERSION = "([^"]+)"'
        if ($m) { $old = $m.Matches[0].Groups[1].Value }
    }
    $new = (Select-String -Path (Join-Path $source "f1tracker\constants.py") -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value

    Write-Host "Installing v$new over v$old (your saves are stored separately and stay untouched)..."
    Copy-Item -Path (Join-Path $source "*") -Destination $here -Recurse -Force
    Write-Host ""
    Write-Host "Updated to v$new. Start run_lan.bat (or run.bat) to play." -ForegroundColor Green
} catch {
    Write-Host "Update failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Nothing was changed if the download failed. You can also update by hand (see UPDATING.txt)."
    exit 1
} finally {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
}
