param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$serverPath = Join-Path $PSScriptRoot 'server.py'
$logFolder = Join-Path $repoRoot '.qa/platform_service'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null

for ($port = 8765; $port -le 8775; $port++) {
    $platformUrl = "http://127.0.0.1:$port"
    try {
        $health = Invoke-RestMethod -Uri "$platformUrl/api/health" -TimeoutSec 1
        if ($health.product -eq 'jiaokesai-platform') {
            if (-not $NoBrowser) { Start-Process $platformUrl }
            Write-Host "Platform is ready: $platformUrl"
            exit 0
        }
    } catch { }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $listener.Start(); $listener.Stop(); break } catch { }
}
if ($port -gt 8775) { throw 'No available local port between 8765 and 8775.' }

$pythonCandidates = @(
    (Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'),
    'D:\python\python.exe'
)
$command = Get-Command python.exe -ErrorAction SilentlyContinue
if ($command) { $pythonCandidates += $command.Source }
$pythonPath = $null
foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    try {
        & $candidate -X utf8 $serverPath --check-runtime *> (Join-Path $logFolder 'runtime.log')
        if ($LASTEXITCODE -eq 0) { $pythonPath = $candidate; break }
    } catch { }
}
if (-not $pythonPath) {
    Write-Host 'Python with NumPy and SciPy is required. See the platform README.'
    Write-Host (Join-Path $logFolder 'runtime.log')
    exit 1
}
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'utf8', ('"' + $serverPath + '"'), '--port', $port) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'server.log') -RedirectStandardError (Join-Path $logFolder 'server-error.log') -PassThru
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "$platformUrl/api/health" -TimeoutSec 1
        if ($health.product -eq 'jiaokesai-platform') {
            if (-not $NoBrowser) { Start-Process $platformUrl }
            Write-Host "Platform is ready: $platformUrl"
            exit 0
        }
    } catch { }
    if ($process.HasExited) { break }
}
Write-Host 'Platform did not start. Check .qa/platform_service/server-error.log.'
exit 1
