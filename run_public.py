"""
EduCloud SaaS — Déploiement & Accès Public Immédiat
Démarre l'application et crée un tunnel Cloudflare sécurisé HTTPS (gratuit, sans compte requis)
accessible depuis n'importe où dans le monde (smartphone, tablette, PC).
"""

import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CLOUDFLARED = BASE_DIR / "cloudflared.exe"


def start_flask():
    """Démarre le serveur Flask EduCloud."""
    import run  # initialise la DB et prépare les variables
    from app import app, init_db
    with app.app_context():
        init_db()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


def monitor_tunnel(proc):
    """Lit la sortie de cloudflared pour extraire l'URL publique HTTPS."""
    url_found = None
    for line in iter(proc.stderr.readline, ''):
        if not line:
            break
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if match and not url_found:
            url_found = match.group(0)
            print("\n" + "=" * 70)
            print(f"  🎉 VOTRE APPLICATION EST ACCESSIBLE PUBLIQUEMENT EN LIGNE !")
            print("=" * 70)
            print(f"\n  👉 LIEN GOOGLE / NAVIGATEUR : {url_found}\n")
            print("  Envoyez ce lien a vos collegues, parents ou testeurs !")
            print("  Ils peuvent se connecter depuis n'importe quel telephone ou PC.")
            print("=" * 70 + "\n")
            
            # Enregistrer le lien dans un fichier texte sur le bureau / dossier
            (BASE_DIR / "LIEN_PUBLIC_ACTIF.txt").write_text(
                f"Lien public EduCloud : {url_found}\nDate : {time.ctime()}\n",
                encoding="utf-8"
            )
            # Ouvrir automatiquement ce lien public dans le navigateur
            try:
                webbrowser.open(url_found)
            except Exception:
                pass


def main():
    if not CLOUDFLARED.exists():
        print("Erreur: cloudflared.exe introuvable dans le dossier.")
        sys.exit(1)

    print("======================================================================")
    print("  🚀 DEMARRAGE D'EDUCLOUD EN MODE ACCES PUBLIC")
    print("======================================================================")
    print("1. Demarrage du serveur local (http://127.0.0.1:5000)...")
    
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(1.5)

    print("2. Creation du lien securise HTTPS mondial via Cloudflare...")
    cmd = [str(CLOUDFLARED), "tunnel", "--url", "http://127.0.0.1:5000"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace"
    )

    t = threading.Thread(target=monitor_tunnel, args=(proc,), daemon=True)
    t.start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nArret du tunnel et de l'application...")
        proc.terminate()


if __name__ == "__main__":
    main()
