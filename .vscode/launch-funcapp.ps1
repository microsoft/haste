param(
  [Parameter(Mandatory = $true)]
  [string]$Folder
)

$ErrorActionPreference = 'Stop'

Push-Location $Folder
try {
  if (-not (Test-Path .venv\Scripts\Activate.ps1)) {
    Write-Host "ERROR: .venv not found in $Folder. Run the one-time venv setup first." -ForegroundColor Red
    exit 1
  }

  & .\.venv\Scripts\Activate.ps1

  $hash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
  $marker = Join-Path .venv '.req-hash'
  $prev = if (Test-Path $marker) { Get-Content $marker -Raw } else { '' }

  if ($prev.Trim() -ne $hash) {
    Write-Host "requirements.txt changed since last run; reinstalling..." -ForegroundColor Yellow
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
      Write-Host "pip install failed (exit $LASTEXITCODE) — not updating hash marker." -ForegroundColor Red
      exit $LASTEXITCODE
    }
    $hash | Set-Content $marker
  }

  func host start
}
finally {
  Pop-Location
}
