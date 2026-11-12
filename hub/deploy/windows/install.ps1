# Install the home hub on Windows as a Task Scheduler task: it starts when you log on, runs hidden
# (pythonw, no console window) and is restarted if it stops with an error.
#   powershell -ExecutionPolicy Bypass -File hub\deploy\windows\install.ps1
# Undo: powershell -ExecutionPolicy Bypass -File hub\deploy\windows\uninstall.ps1
# Needs no admin rights: the task belongs to you and runs only while you are logged on.
$ErrorActionPreference = 'Stop'
$TaskName = 'home-hub'
$HubDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Py = Join-Path $HubDir '.venv\Scripts\python.exe'
$PyW = Join-Path $HubDir '.venv\Scripts\pythonw.exe'
$HomeHub = Join-Path $env:USERPROFILE '.home-hub'

if (-not (Test-Path $PyW)) {
    Write-Host "No venv at $HubDir\.venv. Make it first:"
    Write-Host "  py -3 -m venv hub\.venv"
    Write-Host "  hub\.venv\Scripts\python.exe -m pip install -r hub\hubserver\requirements.txt -r hub\homemcp\requirements.txt"
    exit 1
}
& $Py -c 'import aiohttp, airtouch5py, pychromecast, zeroconf'
if ($LASTEXITCODE -ne 0) {
    Write-Host "The venv is missing packages: $Py -m pip install -r $HubDir\hubserver\requirements.txt"
    exit 1
}

# Stop an older copy of the task first, so its hub frees the port.
$old = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($old) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Start-Sleep -Seconds 2
}
$busy = Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "Something is already listening on port 8790 (process $($busy[0].OwningProcess)). Stop it first (is the hub already running in a window?)."
    exit 1
}

New-Item -ItemType Directory -Force -Path $HomeHub, (Join-Path $HomeHub 'logs') | Out-Null

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $PyW -Argument '-m hubserver' -WorkingDirectory $HubDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Description 'Home hub (http://<this PC>:8790). Starts at logon.' `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed the '$TaskName' task. Checking it answers..."
for ($i = 0; $i -lt 20; $i++) {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8790/api/health' -TimeoutSec 2
        if ($r.ok) {
            Write-Host "The hub is up: http://127.0.0.1:8790/  (log: $HomeHub\logs\hub.log)"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}
Write-Host "The hub did not answer yet. Look at $HomeHub\logs\hub.log and the task's History in Task Scheduler."
exit 1
