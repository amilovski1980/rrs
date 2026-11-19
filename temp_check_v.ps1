Start-Sleep -Seconds 270
try {
    $r = Invoke-WebRequest -Uri 'https://rrs-sandy.vercel.app/v/00000000-0000-0000-0000-000000000000/' -UseBasicParsing -TimeoutSec 45
    Write-Output ("/v/ -> {0} | demo: {1}" -f $r.StatusCode, ($r.Content -match 'FAC-2026-0042'))
} catch {
    Write-Output ("/v/ -> ERREUR {0}" -f [int]$_.Exception.Response.StatusCode)
}
