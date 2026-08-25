param(
    [Parameter(Mandatory = $true)][string]$BaseRoot,
    [Parameter(Mandatory = $true)][string]$HeadRoot,
    [Parameter(Mandatory = $true)][string]$BaseSha,
    [Parameter(Mandatory = $true)][string]$HeadSha,
    [Parameter(Mandatory = $true)][string]$EvidencePath,
    [string]$PythonExecutable = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExactCheckout {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedSha
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $actualLines = @(& git -C $Root rev-parse HEAD 2>&1 | ForEach-Object { $_.ToString() })
    $gitExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    $actualSha = ($actualLines -join "`n").Trim()
    if ($gitExitCode -ne 0 -or $actualSha -ne $ExpectedSha) {
        throw "checkout identity mismatch: expected $ExpectedSha at $Root, got $actualSha"
    }
}

function Invoke-FullGateSample {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][int]$Sequence,
        [Parameter(Mandatory = $true)][string]$CommitSha,
        [Parameter(Mandatory = $true)][string]$Root
    )

    Push-Location -LiteralPath $Root
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $lines = @(& $PythonExecutable -m scripts.quality.verify_core --full 2>&1 | ForEach-Object { $_.ToString() })
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
    }
    finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
    return [ordered]@{
        role = $Role
        sequence = $Sequence
        commitSha = $CommitSha
        exitCode = $exitCode
        output = $lines -join "`n"
    }
}

Assert-ExactCheckout -Root $BaseRoot -ExpectedSha $BaseSha
Assert-ExactCheckout -Root $HeadRoot -ExpectedSha $HeadSha

$samples = @(
    (Invoke-FullGateSample -Role "BASE" -Sequence 1 -CommitSha $BaseSha -Root $BaseRoot),
    (Invoke-FullGateSample -Role "HEAD" -Sequence 1 -CommitSha $HeadSha -Root $HeadRoot),
    (Invoke-FullGateSample -Role "HEAD" -Sequence 2 -CommitSha $HeadSha -Root $HeadRoot),
    (Invoke-FullGateSample -Role "BASE" -Sequence 2 -CommitSha $BaseSha -Root $BaseRoot)
)
$evidence = [ordered]@{
    schemaVersion = "1.0.0"
    samples = $samples
}
$json = $evidence | ConvertTo-Json -Depth 5
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($EvidencePath, $json, $utf8WithoutBom)

Push-Location -LiteralPath $HeadRoot
try {
    & $PythonExecutable -m scripts.quality.timing_gate `
        --evidence $EvidencePath `
        --expected-base-sha $BaseSha `
        --expected-head-sha $HeadSha `
        --limit-seconds 60.0
    $result = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $result
