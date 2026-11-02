# 🏫 Application de Gestion d'École Primaire (Mono-établissement)

Application web de gestion scolaire conforme au cahier des charges de déploiement mono-école (Dr Hamdi Hassen, ISG Sousse). Réalisée avec Python (Flask) et SQLite/PostgreSQL.

---

## 🎯 Fonctionnalités implémentées

### 1. Gestion des Utilisateurs & Contrôle d'Accès (RBAC)
- **6 rôles distincts** : Administrateur / Direction, Enseignant, Parent, Élève, Comptable, Secrétariat.
- Protection CSRF sur l'ensemble des formulaires POST.
- Sessions sécurisées, désactivation de compte avec révocation immédiate de session.
- Espace **Mon profil** pour consultation et modification du mot de passe.
- **Audit Log** : traçabilité de toutes les créations, modifications et suppressions.

### 2. Scolarité & Dossiers Élèves
- **CRUD complet sur toutes les entités** : Élèves, Classes, Matières, Salles.
- Inscription et pré-inscription en ligne avec validation par l'administration/secrétariat.
- Contrôle strict des effectifs et de la capacité maximale des classes.
- Import et export des élèves en format CSV.
- Archivage (suppression logique / soft delete) pour préserver l'historique pluriannuel.

### 3. Emploi du Temps
- Création, modification et suppression de créneaux.
- **Détection des conflits** : impossibilité de programmer un enseignant, une classe ou une salle sur le même créneau horaire.
- Filtrage automatique selon le rôle (enseignant, parent, élève).

### 4. Évaluations, Notes & Bulletins
- Création, modification et suppression des évaluations avec barème configurable.
- Saisie des notes avec contrôle de cohérence.
- **Bulletins de notes scolaires en PDF** téléchargeables avec moyennes pondérées par les coefficients des matières.

### 5. Absences
- Enregistrement des absences par classe et par élève.
- Justification directe des absences par les parents depuis leur espace.
- Modification et suppression des enregistrements par l'administration ou l'enseignant.

### 6. Finances & Comptabilité
- Grille tarifaire par année scolaire (CRUD complet).
- Saisie et historique des paiements (Espèces, Virement, Mobile money).
- **Génération automatique de reçus PDF** avec solde restant calculé en direct.
- **Notification automatique enrichie** au parent (montant, date, mode, solde restant, lien vers le reçu).
- **Export comptable complet en CSV** de toutes les transactions financières.
- **Relance automatique des impayés** : envoi de notifications automatiques aux parents ayant un solde en retard.

### 7. Devoirs (Homework)
- Publication, modification et suppression contrôlée des devoirs par les enseignants.
- Pièces jointes (PDF, documents, images).
- Dépôt de travail par l'élève et correction téléchargeable après la date de remise.
- Notation des devoirs par l'enseignant.

### 8. Messagerie & Communication
- Échanges directs sécurisés selon les permissions RBAC.
- **Brouillons** : enregistrement et modification avant envoi officiel.
- **Immuabilité des messages envoyés** : garantie de traçabilité.
- **Suppression côté destinataire** (masquage de boîte sans altérer la copie expéditeur ni l'historique).
- Envoi et téléchargement sécurisé de pièces jointes.
- Annonces générales ciblées par audience.

---

## 🚀 Lancement en local

1. Cloner ou ouvrir le projet dans votre terminal.
2. Créer l'environnement virtuel et installer les dépendances :

```bash
python -m venv .venv
# Sur Windows :
.venv\Scripts\activate
# Sur Linux / macOS :
source .venv/bin/activate

pip install -r requirements.txt
```

3. Lancer l'application :

```bash
python app.py
```

4. Accéder à l'application sur [http://127.0.0.1:5000](http://127.0.0.1:5000).

---

## 🔑 Comptes de démonstration

La base est automatiquement pré-remplie au premier lancement avec des comptes de test :

| Rôle | Identifiant | Mot de passe | Accès principal |
|---|---|---|---|
| **Administrateur** | `admin` | `admin123` | Tous les modules, configuration, utilisateurs |
| **Comptable** | `comptable` | `compta123` | Module financier, paiements, reçus, relances |
| **Secrétariat** | `secretaire` | `secret123` | Dossiers élèves, pré-inscriptions |
| **Enseignant** | `enseignant` | `prof123` | Classes affectées, notes, devoirs, emploi du temps |
| **Parent** | `parent` / `parent2` | `parent123` | Suivi des enfants, notes, paiements, messagerie |
| **Élève** | `eleve` / `eleve2` | `eleve123` | Devoirs, notes, emploi du temps personnel |

---

## 🧪 Tests unitaires et d'intégration

La suite de tests automatisés vérifie le contrôle d'accès, la sécurité CSRF, le RBAC, les opérations CRUD et la comptabilité :

```bash
python -m unittest discover -s tests -v
```

---

## 🌐 Déploiement en production (Cloud / VPS)

### Option A : Déploiement simple sur Railway / Render
Le projet contient un `Procfile` prêt à l'emploi :
1. Pousser le projet sur un dépôt GitHub privé.
2. Sur [Railway.app](https://railway.app) ou [Render.com](https://render.com), créer un nouveau projet depuis votre dépôt GitHub.
3. Définir les variables d'environnement dans le panneau de configuration :
   - `SECRET_KEY` : une chaîne aléatoire sécurisée (ex: `openssl rand -hex 32`)
   - `COOKIE_SECURE` : `1` (pour forcer les cookies HTTPS)
   - `FLASK_DEBUG` : `0`

### Option B : Déploiement Docker
Un `Dockerfile` est inclus :
```bash
docker build -t ecole-gestion .
docker run -p 5000:5000 -e SECRET_KEY="votre_cle_secrete" ecole-gestion
```
