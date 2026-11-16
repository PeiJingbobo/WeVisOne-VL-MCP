# Start/stop the WeVisOne-VL MCP server as a Windows scheduled task.
# A plain Start-Process child dies with the SSH session; a scheduled task does not.
#
# The shared token is never passed on the command line or baked into the task
# arguments: the task only learns *where* the token lives.
#
#   powershell -File serve.ps1                                     # loopback, no token
#   powershell -File serve.ps1 -BindHost 0.0.0.0 -TokenFile .token  # LAN, token from file
#   powershell -File serve.ps1 -BindHost 0.0.0.0 -TokenFile .token -Rotate
#   powershell -File serve.ps1 -Stop
#
# Autostart (follows the OS boot):
#   powershell -File serve.ps1 -BindHost 0.0.0.0 -TokenFile .token -Autostart
#   powershell -File serve.ps1 -Autostart -AtStartup    # needs an elevated shell
#   powershell -File serve.ps1 -NoAutostart             # forget the autostart intent
#
# The intent is persisted in <root>\.autostart so a later plain run does not
# silently drop the trigger — the task is re-registered on every start.
param(
    [string]$BindHost = '127.0.0.1',
    [string]$TokenFile = '',
    [int]$Port = 8000,
    [switch]$Rotate,
    [switch]$Autostart,
    [switch]$AtStartup,
    [switch]$NoAutostart,
    [switch]$Uninstall,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$root = 'C:\Users\PeiJingbo\MyCode\WeVisOne-VL-MCP'
$python = 'C:\Users\PeiJingbo\AITools\venv-wevisone\Scripts\python.exe'
$taskName = 'WeVisOneMCP'

$markerPath = Join-Path $root '.autostart'

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -Path $markerPath -ErrorAction SilentlyContinue
    Write-Output 'task removed and autostart forgotten'
    return
}

if ($Stop) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Write-Output 'stopped'
    return
}

# Starting a second instance silently fails to bind and the old one keeps serving
# with stale settings, so always tear the previous instance down first.
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($owner in ($existing | Select-Object -ExpandProperty OwningProcess -Unique)) {
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
    }
    $still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($still) {
        Write-Output ("refusing to start: port $Port is still held by pid {0}" -f $still[0].OwningProcess)
        exit 1
    }
}

$tokenPath = if ($TokenFile) {
    if ([System.IO.Path]::IsPathRooted($TokenFile)) { $TokenFile } else { Join-Path $root $TokenFile }
} else { '' }

if ($Rotate) {
    if (-not $tokenPath) {
        Write-Output '-Rotate needs -TokenFile so there is somewhere to write the new token'
        exit 2
    }
    $bytes = New-Object 'byte[]' 24
    # Windows PowerShell 5.1 runs on .NET Framework: no RandomNumberGenerator::Fill.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $newToken = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    Set-Content -Path $tokenPath -Value $newToken -NoNewline -Encoding ascii
    # lock the file down to the current user; a LAN secret readable by everyone is pointless
    # SYSTEM must also read it: an at-startup task runs in that account.
    icacls $tokenPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" "SYSTEM:(R)" | Out-Null
    Write-Output "token rotated into $tokenPath"
}

$hasToken = $false
if ($tokenPath) {
    if (-not (Test-Path $tokenPath)) {
        Write-Output "refusing to start: token file not found at $tokenPath"
        exit 2
    }
    $hasToken = -not [string]::IsNullOrWhiteSpace((Get-Content -Path $tokenPath -Raw))
    if (-not $hasToken) {
        Write-Output "refusing to start: token file $tokenPath is empty"
        exit 2
    }
}

if ($BindHost -notin @('127.0.0.1', 'localhost', '::1') -and -not $hasToken) {
    Write-Output 'refusing a non-loopback bind without a token; pass -TokenFile <path> (add -Rotate to create one)'
    exit 2
}

$envPrefix = "set WEVISONE_MCP_HOST=$BindHost&& set WEVISONE_MCP_PORT=$Port&& "
if ($hasToken) { $envPrefix += "set WEVISONE_MCP_TOKEN_FILE=$tokenPath&& " }
$argument = '/c "' + $envPrefix + '"' + $python + '" -u -m wevisone_mcp.server 1> server.log 2> server.err"'

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $argument -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Autostart intent survives re-registration through a marker file, so a later
# plain `serve.ps1` run cannot silently drop the trigger.
if ($NoAutostart) { Remove-Item -Path $markerPath -ErrorAction SilentlyContinue }
if ($AtStartup) { Set-Content -Path $markerPath -Value 'startup' -Encoding ascii -NoNewline }
elseif ($Autostart) { Set-Content -Path $markerPath -Value 'logon' -Encoding ascii -NoNewline }
$autostartMode = if (Test-Path $markerPath) { (Get-Content -Path $markerPath -Raw).Trim() } else { '' }

$registerArgs = @{ TaskName = $taskName; Action = $action; Settings = $settings; Force = $true }
switch ($autostartMode) {
    'logon' {
        # runs when this user logs on; no elevation needed
        $registerArgs['Trigger'] = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
    }
    'startup' {
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $isAdmin) {
            Write-Output 'refusing -AtStartup from a non-elevated shell: boot-time start needs administrator rights'
            Write-Output 'use -Autostart (starts at logon, no elevation) or re-run this command elevated'
            exit 2
        }
        # SYSTEM runs the service, so it must be able to read the token file even
        # when the file predates this change or was rotated elsewhere.
        if ($hasToken) { icacls $tokenPath /grant "SYSTEM:(R)" | Out-Null }
        $registerArgs['Trigger'] = @(New-ScheduledTaskTrigger -AtStartup)
        $registerArgs['Principal'] = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    }
}

Register-ScheduledTask @registerArgs | Out-Null
Start-ScheduledTask -TaskName $taskName

# Startup preloads the model before binding, so allow a generous window.
$listening = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) { break }
}
if ($listening) {
    Write-Output ("listening on {0}:{1} (pid {2}) token={3}" -f `
        $listening[0].LocalAddress, $Port, $listening[0].OwningProcess, $hasToken)
    switch ($autostartMode) {
        'logon' { Write-Output 'autostart: on (at logon)' }
        'startup' { Write-Output 'autostart: on (at startup, SYSTEM)' }
        default { Write-Output 'autostart: off (pass -Autostart to enable)' }
    }
} else {
    Write-Output 'NOT listening; log tail:'
    Get-Content (Join-Path $root 'server.log') -Tail 20 -ErrorAction SilentlyContinue
    Get-Content (Join-Path $root 'server.err') -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}
