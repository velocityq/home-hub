# Stop the home hub and remove its Task Scheduler task. Your keys and settings stay in %USERPROFILE%\.home-hub.
#   powershell -ExecutionPolicy Bypass -File hub\deploy\windows\uninstall.ps1
$TaskName = 'home-hub'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "There is no '$TaskName' task. Nothing to remove."
    exit 0
}
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Start-Sleep -Seconds 1
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:8790/api/health' -TimeoutSec 2 | Out-Null
    Write-Host "Removed the task, but something still answers on port 8790 (a hub started by hand?)."
} catch {
    Write-Host "Removed the '$TaskName' task and stopped the hub. Your keys and settings stay in $env:USERPROFILE\.home-hub"
}
