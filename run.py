"""
Launcher optimisé pour EduCloud SaaS
Ouvre l'application directement et ultra-rapidement dans votre navigateur web par défaut avec le logo officiel.
"""

import os
import sys
import threading
import time
import webbrowser
from app import app, init_db

PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "127.0.0.1")
URL = f"http://{HOST}:{PORT}"


def open_browser():
    """Attendre un bref instant pour que le serveur soit prêt puis ouvrir le navigateur."""
    time.sleep(0.7)
    try:
        print(f"\n[+] Ouverture automatique du navigateur sur {URL} ...")
        webbrowser.open(URL, new=2)
    except Exception as exc:
        print(f"[!] Erreur lors de l'ouverture du navigateur : {exc}")


def print_banner():
    banner = f"""
======================================================================
  🏫  EDUCLOUD SAAS — SYSTÈME DE GESTION SCOLAIRE PRIMAIRE
======================================================================
  [*] Serveur démarré avec succès !
  [*] URL locale : {URL}
  [*] Logo et favicon intégrés directement dans le navigateur.

  COMPTES DE DÉMONSTRATION :
  -------------------------------------------------------------
  - Administrateur  : admin / admin123
  - Enseignant      : dupont / pass123
  - Parent          : parent1 / pass123
  - Élève           : eleve1 / pass123

  (Appuyez sur Ctrl + C pour arrêter le serveur)
======================================================================
"""
    print(banner)


if __name__ == "__main__":
    # Assurer que la base de données est prête
    with app.app_context():
        init_db()

    # Démarrer le thread d'ouverture du navigateur
    opener = threading.Thread(target=open_browser, daemon=True)
    opener.start()

    print_banner()

    # Démarrer Flask en mode multi-threadé pour des temps de réponse instantanés
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
