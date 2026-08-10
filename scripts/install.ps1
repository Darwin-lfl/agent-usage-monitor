param(
    [string]$Repository = $(if ($env:AGENT_MONITOR_REPOSITORY) { $env:AGENT_MONITOR_REPOSITORY } else { "__REPOSITORY__" }),
    [string]$InstallDir = $(if ($env:AGENT_MONITOR_INSTALL_DIR) { $env:AGENT_MONITOR_INSTALL_DIR } else { "$env:LOCALAPPDATA\Programs\AgentUsageMonitor" }),
    [string]$Version = $(if ($env:AGENT_MONITOR_VERSION) { $env:AGENT_MONITOR_VERSION } else { "latest" })
)

$ErrorActionPreference = "Stop"
if ($Repository -notmatch "^[^/]+/[^/]+$") {
    throw "Installer has not been stamped. Set AGENT_MONITOR_REPOSITORY=owner/repository and retry."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Agent Usage Monitor requires 64-bit Windows."
}

$asset = "agent-monitor-windows-x86_64.zip"
$baseUrl = if ($Version -eq "latest") {
    "https://github.com/$Repository/releases/latest/download"
} else {
    "https://github.com/$Repository/releases/download/$Version"
}
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ("agent-monitor-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tempDir | Out-Null

try {
    $archive = Join-Path $tempDir $asset
    $checksums = Join-Path $tempDir "SHA256SUMS"
    Invoke-WebRequest -UseBasicParsing "$baseUrl/$asset" -OutFile $archive
    Invoke-WebRequest -UseBasicParsing "$baseUrl/SHA256SUMS" -OutFile $checksums
    $line = Get-Content $checksums | Where-Object { $_ -match "\s+$([regex]::Escape($asset))$" } | Select-Object -First 1
    if (-not $line) { throw "No checksum was published for $asset." }
    $expected = ($line -split "\s+")[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Checksum verification failed for $asset." }

    Expand-Archive -Path $archive -DestinationPath $tempDir -Force
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item (Join-Path $tempDir "agent-monitor.exe") (Join-Path $InstallDir "agent-monitor.exe") -Force
    Set-Content -Path (Join-Path $InstallDir "amon.cmd") -Value '@"%~dp0agent-monitor.exe" %*' -Encoding ASCII

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $pathEntries = @($userPath -split ";" | Where-Object { $_ })
    if ($InstallDir -notin $pathEntries) {
        [Environment]::SetEnvironmentVariable("Path", (($pathEntries + $InstallDir) -join ";"), "User")
    }
    $env:Path = "$InstallDir;$env:Path"
    Write-Host "Installed Agent Usage Monitor to $InstallDir\agent-monitor.exe"
    Write-Host "Run: agent-monitor"
    Write-Host "Web: agent-monitor web"
} finally {
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}
