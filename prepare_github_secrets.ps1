# Run this yourself locally (not via me) - it only prints to YOUR screen,
# nothing is sent anywhere. Copy each value into:
#   GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret
#
# Usage: powershell -ExecutionPolicy Bypass -File prepare_github_secrets.ps1

function Show-Secret($name, $value) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    Write-Host $value
}

function Show-FileAsBase64($name, $path) {
    if (Test-Path $path) {
        $bytes = [System.IO.File]::ReadAllBytes($path)
        $b64 = [Convert]::ToBase64String($bytes)
        Write-Host "`n=== $name ===" -ForegroundColor Cyan
        Write-Host $b64
    } else {
        Write-Host "`n=== $name ===" -ForegroundColor Yellow
        Write-Host "SKIPPED - file not found: $path"
    }
}

# --- Plain-text secrets, read straight from your local .env ---
$envLines = Get-Content .env | Where-Object { $_ -match '=' }
$envMap = @{}
foreach ($line in $envLines) {
    $parts = $line -split '=', 2
    $envMap[$parts[0].Trim()] = $parts[1].Trim()
}

Show-Secret "AMAZON_ADS_EMAIL" $envMap["AMAZON_ADS_EMAIL"]
Show-Secret "AMAZON_ADS_PASSWORD" $envMap["AMAZON_ADS_PASSWORD"]
Show-Secret "AMAZON_ADS_TOTP_SECRET" $envMap["AMAZON_ADS_TOTP_SECRET"]
Show-Secret "AMAZON_ADS_BASE_URL" $envMap["AMAZON_ADS_BASE_URL"]
Show-Secret "HECTOR_EMAIL" $envMap["HECTOR_EMAIL"]
Show-Secret "HECTOR_PASSWORD" $envMap["HECTOR_PASSWORD"]
Show-Secret "HECTOR_BASE_URL" $envMap["HECTOR_BASE_URL"]

# --- File-based secrets, base64-encoded ---
Show-FileAsBase64 "GOOGLE_SERVICE_ACCOUNT_JSON_B64" "data-reconciliation-510312-70a744333ac6.json"
Show-FileAsBase64 "STORAGE_STATE_CAMPUS_B64" "storage_state_campus.json"
Show-FileAsBase64 "STORAGE_STATE_BBE_US_B64" "storage_state_bbe-us.json"
Show-FileAsBase64 "STORAGE_STATE_HECTOR_B64" "storage_state_hector.json"
Show-FileAsBase64 "HECTOR_MCP_TOKEN_B64" "hector_mcp_token.json"

Write-Host "`n`nDone. Create each secret above (exact name shown) in:" -ForegroundColor Green
Write-Host "GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret"
