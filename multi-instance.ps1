# multi-instance.ps1
$instances = Read-Host "How many OpenAlgo instances do you want to set up?"
if (-not ($instances -as [int]) -or [int]$instances -le 0) {
    Write-Host "Invalid number. Please enter a positive integer."
    exit
}
$instances = [int]$instances
$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoUrl = "https://github.com/marketcalls/openalgo.git"
$flaskPortBase = 5000
$wsPortBase    = 8765
$zmqPortBase   = 5555
for ($i = 1; $i -le $instances; $i++) {
    $folder = Join-Path $baseDir "openalgo$i"
    $envFile = Join-Path $folder ".env"
    $sampleFile = Join-Path $folder ".sample.env"
    if (-not (Test-Path $folder)) { git clone $repoUrl $folder | Out-Null }
    if (-not (Test-Path $envFile)) { Copy-Item $sampleFile $envFile -Force }
    $appKey = (python -c "import secrets; print(secrets.token_hex(32))").Trim()
    $pepper = (python -c "import secrets; print(secrets.token_hex(32))").Trim()
    $flaskPort = $flaskPortBase + ($i - 1)
    $wsPort    = $wsPortBase + ($i - 1)
    $zmqPort   = $zmqPortBase + ($i - 1)
    $sessionCookie = "session$i"
    $csrfCookie    = "csrf_token$i"
    $dbPath = "sqlite:///db/openalgo$i.db"
    $latencyDB = "sqlite:///db/latency$i.db"
    $logsDB = "sqlite:///db/logs$i.db"
    $sandboxDB = "sqlite:///db/sandbox.db"
    $historifyDB = "sqlite:///db/historify.duckdb"
    $content = Get-Content $envFile
    $content = $content -replace "127.0.0.1:5000", "127.0.0.1:$flaskPort"
    $content = $content -replace "FLASK_PORT='[0-9]+'", "FLASK_PORT='$flaskPort'"
    $content = $content -replace "WEBSOCKET_PORT='[0-9]+'", "WEBSOCKET_PORT='$wsPort'"
    $content = $content -replace "ws://127.0.0.1:[0-9]+", "ws://127.0.0.1:$wsPort"
    $content = $content -replace "ZMQ_PORT='[0-9]+'", "ZMQ_PORT='$zmqPort'"
    $content = $content -replace "SESSION_COOKIE_NAME = '.*'", "SESSION_COOKIE_NAME = '$sessionCookie'"
    $content = $content -replace "CSRF_COOKIE_NAME = '.*'", "CSRF_COOKIE_NAME = '$csrfCookie'"
    $content = $content -replace "DATABASE_URL = '.*'", "DATABASE_URL = '$dbPath'"
    $content = $content -replace "LATENCY_DATABASE_URL = '.*'", "LATENCY_DATABASE_URL = '$latencyDB'"
    $content = $content -replace "LOGS_DATABASE_URL = '.*'", "LOGS_DATABASE_URL = '$logsDB'"
    $content = $content -replace "SANDBOX_DATABASE_URL = '.*'", "SANDBOX_DATABASE_URL = '$sandboxDB'"
    $content = $content -replace "HISTORIFY_DATABASE_URL = '.*'", "HISTORIFY_DATABASE_URL = '$historifyDB'"
    $content = $content -replace "(?<=APP_KEY = ')[^']+", $appKey
    $content = $content -replace "(?<=API_KEY_PEPPER = ')[^']+", $pepper
    Set-Content $envFile $content
    Write-Host "Configured openalgo$i → Flask:$flaskPort | WS:$wsPort | ZMQ:$zmqPort | DB: openalgo$i.db"
}
