function Get-ValidatedScreenshotAlignerProcess {
    param([Parameter(Mandatory = $true)][string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $PidValue = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $ParsedPid = 0
    if (-not [int]::TryParse($PidValue, [ref]$ParsedPid)) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $Instance = Get-CimInstance Win32_Process -Filter "ProcessId = $ParsedPid" -ErrorAction SilentlyContinue
    if (-not $Instance) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $Identity = "$($Instance.Name) $($Instance.ExecutablePath) $($Instance.CommandLine)"
    if ($Identity -notmatch '(?i)screenshot[-_]?aligner') {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    return Get-Process -Id $ParsedPid -ErrorAction SilentlyContinue
}

function Get-DiscoveredScreenshotAlignerProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '(?i)^screenshot[-_]?aligner\.exe$' } |
        ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}
