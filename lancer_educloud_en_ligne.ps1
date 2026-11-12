# ======================================================================
# EduCloud SaaS - Lancement du Service Cloud en Ligne
# ======================================================================

$Host.UI.RawUI.WindowTitle = "EduCloud SaaS - Service Cloud Public"
Set-Location -Path $PSScriptRoot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          EDUCLOUD SAAS - PLATEFORME DE GESTION SCOLAIRE" -ForegroundColor White
Write-Host "                Lancement du Service Cloud Public" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Vérification python
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "[ERREUR] L'environnement .venv est introuvable." -ForegroundColor Red
    pause
    exit
}

# 2. Démarrage de Flask
Write-Host "[1/2] Démarrage du serveur EduCloud..." -ForegroundColor Green
$flaskProcess = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "app.py" -PassThru

Start-Sleep -Seconds 2

# 3. Démarrage de Cloudflare Tunnel
Write-Host "[2/2] Activation du tunnel Cloudflare (accès public internet mondial)..." -ForegroundColor Green
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host "VOTRE APPLICATION SERA ACCESSIBLE PARTOUT DANS LE MONDE VIA L'URL :" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host ""

if (Test-Path ".\cloudflared.exe") {
    & ".\cloudflared.exe" tunnel --url http://127.0.0.1:5000
} else {
    Write-Host "cloudflared.exe non trouvé. Accès local : http://localhost:5000" -ForegroundColor Yellow
}
