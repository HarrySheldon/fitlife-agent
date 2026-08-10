[CmdletBinding()]
param(
    [switch]$InitializeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$script:EnvPath = Join-Path $script:ProjectRoot ".env"
$script:EnvExamplePath = Join-Path $script:ProjectRoot ".env.example"
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Invoke-Startup {
    Assert-EnvironmentFileIsPrivate
    Initialize-Environment
    Write-Host "Local environment is ready. The deployment encryption key is configured."

    if ($InitializeOnly) {
        return
    }

    Assert-DockerCommand
    Wait-ForDockerEngine

    Push-Location $script:ProjectRoot
    try {
        & docker compose up --build -d
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose failed. Run 'docker compose ps' for container status."
        }
    }
    finally {
        Pop-Location
    }

    $backendPort = Get-ConfiguredPort -Name "BACKEND_PORT" -DefaultValue 8000
    $frontendPort = Get-ConfiguredPort -Name "FRONTEND_PORT" -DefaultValue 3000
    $backendUrl = "http://127.0.0.1:$backendPort"
    $frontendUrl = "http://127.0.0.1:$frontendPort"

    Wait-ForCondition `
        -Description "backend readiness" `
        -TimeoutSeconds 120 `
        -Condition { Test-BackendReady -Url "$backendUrl/health/ready" }
    Wait-ForCondition `
        -Description "frontend health" `
        -TimeoutSeconds 120 `
        -Condition { Test-HttpSuccess -Url $frontendUrl }

    Write-Host "FitLife Agent is ready."
    Write-Host "Frontend: $frontendUrl"
    Write-Host "Backend:  $backendUrl"
    Write-Host "Health:   $backendUrl/health/ready"
}

function Assert-EnvironmentFileIsPrivate {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $git) {
        $insideRepository = Invoke-QuietNative {
            & git -C $script:ProjectRoot rev-parse --is-inside-work-tree
        }
        if ($insideRepository -eq 0) {
            $trackedEnv = & git -C $script:ProjectRoot ls-files -- .env
            if ($trackedEnv) {
                throw ".env is tracked by Git. Remove it from the index before startup."
            }

            $ignored = Invoke-QuietNative {
                & git -C $script:ProjectRoot check-ignore -q -- .env
            }
            if ($ignored -ne 0) {
                throw ".env is not ignored by Git. Add it to .gitignore before startup."
            }
            return
        }
    }

    $ignorePath = Join-Path $script:ProjectRoot ".gitignore"
    if (-not (Test-Path -LiteralPath $ignorePath -PathType Leaf)) {
        throw ".env is not ignored because .gitignore is missing."
    }
    $patterns = [System.IO.File]::ReadAllLines($ignorePath)
    $ignored = $patterns | Where-Object {
        $pattern = $_.Trim()
        $pattern -in @(".env", ".env*", "**/.env", "**/.env*")
    }
    if (-not $ignored) {
        throw ".env is not ignored by Git. Add it to .gitignore before startup."
    }
}

function Initialize-Environment {
    if (-not (Test-Path -LiteralPath $script:EnvPath -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $script:EnvExamplePath -PathType Leaf)) {
            throw ".env.example is missing."
        }
        $example = [System.IO.File]::ReadAllText($script:EnvExamplePath)
        Write-AtomicText -Path $script:EnvPath -Content $example
    }

    $lines = [System.IO.File]::ReadAllLines($script:EnvPath)
    $keyIndexes = @()
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^SETTINGS_ENCRYPTION_KEY=(.*)$') {
            $keyIndexes += $index
        }
    }
    if ($keyIndexes.Count -gt 1) {
        throw ".env contains duplicate SETTINGS_ENCRYPTION_KEY entries."
    }

    $current = ""
    if ($keyIndexes.Count -eq 1) {
        $current = $lines[$keyIndexes[0]].Substring("SETTINGS_ENCRYPTION_KEY=".Length).Trim()
    }
    if ($current) {
        if (-not (Test-FernetKey -Value $current)) {
            throw "The existing SETTINGS_ENCRYPTION_KEY is invalid and was not changed."
        }
        return
    }

    $secret = New-FernetKey
    if ($keyIndexes.Count -eq 1) {
        $lines[$keyIndexes[0]] = "SETTINGS_ENCRYPTION_KEY=$secret"
    }
    else {
        $lines += "SETTINGS_ENCRYPTION_KEY=$secret"
    }
    $content = ($lines -join [Environment]::NewLine) + [Environment]::NewLine
    Write-AtomicText -Path $script:EnvPath -Content $content
}

function New-FernetKey {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

function Test-FernetKey {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^[A-Za-z0-9_-]{43}=$') {
        return $false
    }
    try {
        $standard = $Value.Replace("-", "+").Replace("_", "/")
        return ([Convert]::FromBase64String($standard).Length -eq 32)
    }
    catch {
        return $false
    }
}

function Write-AtomicText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $operationId = [Guid]::NewGuid().ToString('N')
    $temporary = "$Path.tmp.$PID.$operationId"
    $backup = "$Path.backup.$PID.$operationId"
    try {
        [System.IO.File]::WriteAllText($temporary, $Content, $script:Utf8NoBom)
        if (Test-Path -LiteralPath $Path) {
            [System.IO.File]::Replace($temporary, $Path, $backup)
        }
        else {
            [System.IO.File]::Move($temporary, $Path)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Force
        }
    }
}

function Assert-DockerCommand {
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is not installed or is not available on PATH."
    }
    $composeAvailable = Invoke-QuietNative { & docker compose version }
    if ($composeAvailable -ne 0) {
        throw "The Docker Compose plugin is not available."
    }
}

function Wait-ForDockerEngine {
    if (Test-DockerReady) {
        return
    }

    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $desktop -PathType Leaf)) {
        throw "Docker engine is not running and Docker Desktop was not found."
    }
    Write-Host "Starting Docker Desktop..."
    Start-Process -FilePath $desktop -WindowStyle Hidden
    Wait-ForCondition `
        -Description "Docker engine" `
        -TimeoutSeconds 120 `
        -Condition { Test-DockerReady }
}

function Test-DockerReady {
    return ((Invoke-QuietNative { & docker info }) -eq 0)
}

function Invoke-QuietNative {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $Command *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-ConfiguredPort {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$DefaultValue
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not $value) {
        foreach ($line in [System.IO.File]::ReadAllLines($script:EnvPath)) {
            if ($line -match "^$Name=(.*)$") {
                $value = $Matches[1].Trim()
            }
        }
    }
    if (-not $value) {
        return $DefaultValue
    }
    $port = 0
    if (-not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "$Name must be an integer between 1 and 65535."
    }
    return $port
}

function Wait-ForCondition {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][scriptblock]$Condition
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Condition) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $Description. Run 'docker compose ps' for status."
}

function Test-BackendReady {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3 -Method Get
        return ($response.success -eq $true -and $response.data.status -eq "ready")
    }
    catch {
        return $false
    }
}

function Test-HttpSuccess {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 -Method Get
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

try {
    Invoke-Startup
}
catch {
    [Console]::Error.WriteLine("Startup failed: {0}", $_.Exception.Message)
    exit 1
}
