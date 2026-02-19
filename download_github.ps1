param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    
    [Parameter(Mandatory=$true)]
    [string]$OutputFile
)

try {
    Write-Host "Downloading from GitHub..." -ForegroundColor Cyan
    Write-Host "URL: $Url" -ForegroundColor Gray
    Write-Host "Output: $OutputFile" -ForegroundColor Gray
    
    Invoke-WebRequest -Uri $Url -OutFile $OutputFile -UseBasicParsing -ErrorAction Stop
    
    if (Test-Path $OutputFile) {
        $size = (Get-Item $OutputFile).Length
        Write-Host "SUCCESS: Downloaded $size bytes" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "ERROR: File not created" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
