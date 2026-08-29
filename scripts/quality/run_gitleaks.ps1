param(
    [switch]$Advisory,
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "../.."))
)

$ErrorActionPreference = "Stop"
$Version = "8.30.1"
$ExpectedSha256 = "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e"
$asset = "gitleaks_$Version`_windows_x64.zip"
$url = "https://github.com/gitleaks/gitleaks/releases/download/v$Version/$asset"
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("e1b-gitleaks-" + [guid]::NewGuid())
$archive = Join-Path $temporaryRoot $asset
$toolRoot = Join-Path $temporaryRoot "tool"
$snapshotArchive = Join-Path $temporaryRoot "current-tree.zip"
$snapshotRoot = Join-Path $temporaryRoot "current-tree"
$reportsRoot = Join-Path $temporaryRoot "reports"
$findingCount = 0

function Invoke-RedactedScan {
    param([string[]]$Arguments, [string]$ReportPath)
    & $script:Executable @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        return
    }
    if ($exitCode -eq 1 -and (Test-Path -LiteralPath $ReportPath)) {
        $report = Get-Content -Raw -LiteralPath $ReportPath | ConvertFrom-Json
        if ($null -ne $report -and @($report).Count -gt 0) {
            $script:findingCount += @($report).Count
            return
        }
    }
    throw "Gitleaks execution failed closed with exit code $exitCode"
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot, $toolRoot, $snapshotRoot, $reportsRoot | Out-Null
    Invoke-WebRequest -Uri $url -OutFile $archive
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $ExpectedSha256) {
        throw "Gitleaks archive integrity mismatch"
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $toolRoot
    $script:Executable = Join-Path $toolRoot "gitleaks.exe"
    if (-not (Test-Path -LiteralPath $script:Executable)) {
        throw "Verified Gitleaks archive did not contain gitleaks.exe"
    }

    & git -C $Root archive --format=zip --output=$snapshotArchive HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create tracked current-tree snapshot"
    }
    Expand-Archive -LiteralPath $snapshotArchive -DestinationPath $snapshotRoot

    $currentReport = Join-Path $reportsRoot "current-tree.json"
    Invoke-RedactedScan -ReportPath $currentReport -Arguments @(
        "dir", "--config", (Join-Path $Root ".gitleaks.toml"), "--redact=100",
        "--report-format", "json", "--report-path", $currentReport, "--no-banner", $snapshotRoot
    )

    $historyReport = Join-Path $reportsRoot "reachable-history.json"
    Invoke-RedactedScan -ReportPath $historyReport -Arguments @(
        "git", "--config", (Join-Path $Root ".gitleaks.toml"), "--redact=100",
        "--report-format", "json", "--report-path", $historyReport, "--no-banner",
        "--log-opts=--all", $Root
    )

    Write-Output "GITLEAKS_VERSION=$Version"
    Write-Output "GITLEAKS_FINDING_COUNT=$findingCount"
    if ($findingCount -gt 0 -and -not $Advisory) {
        exit 1
    }
    exit 0
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -Recurse -Force -LiteralPath $temporaryRoot
    }
}
