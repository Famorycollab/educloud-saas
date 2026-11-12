@echo off
chcp 65001 > nul
title EduCloud SaaS - Lancement du Service Cloud en Ligne
color 0B

echo ======================================================================
echo           EDUCLOUD SAAS - PLATEFORME DE GESTION SCOLAIRE
echo                 Lancement du Service Cloud Public
echo ======================================================================
echo.

cd /d "%~dp0"

echo [1/3] Verification de l'environnement virtuel Python...
if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] L'environnement .venv est introuvable.
    pause
    exit /b 1
)

echo [2/3] Demarrage du serveur EduCloud sur http://127.0.0.1:5000 ...
start "EduCloud Web Server" cmd /k ".\.venv\Scripts\python.exe app.py"

timeout /t 2 /nobreak > nul

echo [3/3] Creation du Tunnel Cloud Public securise (Cloudflare)...
echo.
echo ======================================================================
echo VOTRE APPLICATION EST ACCESSIBLE VIA LE LIEN QUI VA S'AFFICHER CI-DESSOUS :
echo (Copiez l'URL .trycloudflare.com et partagez-la a vos utilisateurs)
echo ======================================================================
echo.

if exist "cloudflared.exe" (
    .\cloudflared.exe tunnel --url http://127.0.0.1:5000
) else (
    echo [INFO] cloudflared.exe non trouve, acces local uniquement sur http://localhost:5000
    pause
)
