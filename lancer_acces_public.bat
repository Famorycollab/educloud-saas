@echo off
title EduCloud - Deploiement & Lien Public
cd /d "%~dp0"
echo ==========================================================
echo   Lancement du deploiement public instantane EduCloud
echo ==========================================================
python run_public.py
pause
