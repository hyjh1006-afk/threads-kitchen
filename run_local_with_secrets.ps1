param(
    [string]$PythonCode = "",
    [string]$EntryPoint = "publish_daily.py",
    [string[]]$EntryArgs = @()
)

$ErrorActionPreference = "Stop"
$secretFile = Join-Path $PSScriptRoot ".local-secrets\bluesky_app_password.dpapi"

if (-not (Test-Path -LiteralPath $secretFile)) {
    throw "Encrypted Bluesky credential is missing: $secretFile"
}

$secureValue = Get-Content -Raw -LiteralPath $secretFile | ConvertTo-SecureString
$secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)

try {
    $env:BLUESKY_HANDLE = "pparkzze.bsky.social"
    $env:BLUESKY_APP_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
    if ($PythonCode) {
        & python -c $PythonCode
    }
    else {
        & python $EntryPoint @EntryArgs
    }
    exit $LASTEXITCODE
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
    Remove-Item Env:\BLUESKY_APP_PASSWORD -ErrorAction SilentlyContinue
}
