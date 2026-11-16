# Verify remote mode end to end: start a proxy instance that forwards to the real
# service, drive it over REST, then tear it down.
#
#   powershell -File verify_remote_mode.ps1 [-Upstream http://127.0.0.1:8000] [-Port 9000]
param(
    [string]$Upstream = 'http://127.0.0.1:8000',
    [int]$Port = 9000,
    [string]$Image = ''
)

$ErrorActionPreference = 'Stop'
$root = 'C:\Users\PeiJingbo\MyCode\WeVisOne-VL-MCP'
$python = 'C:\Users\PeiJingbo\AITools\venv-wevisone\Scripts\python.exe'
$token = (Get-Content (Join-Path $root '.token') -Raw).Trim()

$env:WEVISONE_MCP_HOST = '127.0.0.1'
$env:WEVISONE_MCP_PORT = "$Port"
$env:WEVISONE_MCP_TOKEN_FILE = Join-Path $root '.token'
$env:WEVISONE_REMOTE_URL = $Upstream
$env:WEVISONE_REMOTE_TOKEN = $token
$env:WEVISONE_PRELOAD = '0'

Write-Output "starting proxy on 127.0.0.1:$Port -> $Upstream"
$process = Start-Process -FilePath $python -ArgumentList '-u', '-m', 'wevisone_mcp.server' `
    -WorkingDirectory $root -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root 'proxy.log') `
    -RedirectStandardError (Join-Path $root 'proxy.err')

try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Output 'FAIL proxy did not start; log tail:'
        Get-Content (Join-Path $root 'proxy.log') -Tail 10 -ErrorAction SilentlyContinue
        Get-Content (Join-Path $root 'proxy.err') -Tail 10 -ErrorAction SilentlyContinue
        exit 1
    }
    Write-Output 'proxy listening'

    $log = Get-Content (Join-Path $root 'proxy.log') -Raw
    if ($log -notmatch 'remote ->') { Write-Output 'WARN log does not show remote mode' }

    $headers = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }

    # doctor via the proxy's own REST surface. PowerShell 5.1 has no
    # -SkipHttpErrorCheck, so read the error body from the exception instead.
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/predict" -Method Post -Headers $headers `
            -Body '{"task":"unknown-task","query":""}' | Out-Null
        Write-Output 'doctor through proxy: unexpected 2xx for an invalid task'
    }
    catch {
        $response = $_.Exception.Response
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $body = $reader.ReadToEnd()
        $reader.Close()
        Write-Output ("doctor through proxy (HTTP {0}): {1}" -f [int]$response.StatusCode, $body)
    }

    # real prediction through the proxy
    if ($Image -and (Test-Path $Image)) {
        $bytes = [System.IO.File]::ReadAllBytes($Image)
        $body = @{ image_base64 = [Convert]::ToBase64String($bytes); task = 'segmentation'; query = 'sofa' } |
            ConvertTo-Json -Compress
        $result = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/predict" -Method Post -Headers $headers -Body $body
        Write-Output ("predict through proxy: ok={0} boxes={1} artifacts={2} latency={3}s" -f `
            $result.ok, ($result.boxes | ConvertTo-Json -Compress), $result.artifact_count, $result.latency_s)
        if ($result.artifact_count -gt 0) {
            $artifactUrl = "http://127.0.0.1:$Port" + $result.artifacts[0].url
            # -UseBasicParsing: PowerShell 5.1 otherwise needs the IE engine
            $resp = Invoke-WebRequest -Uri $artifactUrl -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing
            Write-Output ("artifact through proxy: HTTP {0}, {1} bytes" -f $resp.StatusCode, $resp.RawContentLength)
        }
    } else {
        Write-Output 'SKIP real prediction (no -Image)'
    }

    # upload passthrough
    if ($Image -and (Test-Path $Image)) {
        $upload = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/upload" -Method Post `
            -Headers @{ Authorization = "Bearer $token" } -InFile $Image
        Write-Output ("upload through proxy: ok={0} id={1} bytes={2}" -f $upload.ok, $upload.upload_id, $upload.bytes)
    }
}
finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    Write-Output 'proxy stopped'
}
