import os
import sqlite3
import json
import math
import re
import secrets
import uuid
import calendar as py_calendar
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, make_response, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "school.db"
app = Flask(__name__, template_folder="app/templates", static_folder="app/static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["UPLOAD_FOLDER"] = str(BASE_DIR / "private_uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
ALLOWED_UPLOADS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "odt"}
PUBLIC_REGISTER_ROLES = ("parent", "student", "teacher")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_iso_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Date au format AAAA-MM-JJ requise.")
    return parsed


def is_valid_birth_date(value):
    if not value:
        return True
    try:
        return parse_iso_date(value) <= date.today()
    except (TypeError, ValueError):
        return False


def save_upload(upload):
    if not upload or not upload.filename:
        return ""
    safe_name = secure_filename(upload.filename)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in ALLOWED_UPLOADS:
        raise ValueError("Type de fichier non autorisé.")
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    upload.save(Path(app.config["UPLOAD_FOLDER"]) / stored_name)
    return stored_name


def student_account_available(user_id, exclude_student_id=None):
    if not user_id:
        return True
    return bool(get_db().execute(
        "SELECT 1 FROM users u WHERE u.id=? AND u.role='student' AND u.active=1 "
        "AND NOT EXISTS(SELECT 1 FROM students s WHERE s.student_user_id=u.id "
        "AND (? IS NULL OR s.id<>?))",
        (user_id, exclude_student_id, exclude_student_id),
    ).fetchone())


def audit(action, entity, entity_id=None, old_values=None, new_values=None):
    get_db().execute("INSERT INTO audit_log(user_id,action,entity,entity_id,old_values,new_values,created_at) VALUES(?,?,?,?,?,?,?)",(session.get("user_id"),action,entity,entity_id,json.dumps(old_values or {},ensure_ascii=False),json.dumps(new_values or {},ensure_ascii=False),datetime.now().isoformat(timespec="seconds")))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=60.0)
        g.db.row_factory = sqlite3.Row
        try:
            g.db.execute("PRAGMA journal_mode = WAL")
            g.db.execute("PRAGMA busy_timeout = 60000")
            g.db.execute("PRAGMA foreign_keys = ON")
        except sqlite3.OperationalError:
            pass
    return g.db


@app.before_request
def protect_post_requests():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)

    if request.method == "POST":
        submitted = request.form.get("csrf_token", "") or request.headers.get("X-CSRFToken", "") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not submitted or not secrets.compare_digest(submitted, expected):
            abort(400, description="Jeton de sécurité invalide. Rechargez la page et réessayez.")

    # Multi-tenant scoping
    if session.get("user_id"):
        db = get_db()
        school_id = session.get("school_id")
        if not school_id:
            u = db.execute("SELECT school_id FROM users WHERE id=?", (session["user_id"],)).fetchone()
            school_id = u["school_id"] if (u and "school_id" in u.keys() and u["school_id"]) else 1
            session["school_id"] = school_id
        
        school = db.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
        if not school:
            school = db.execute("SELECT * FROM schools LIMIT 1").fetchone()
            if school:
                school_id = school["id"]
                session["school_id"] = school_id
        
        g.school_id = school_id
        g.current_school = school
        if session.get("role") in ("superadmin", "director", "admin"):
            g.accessible_schools = db.execute("SELECT * FROM schools WHERE active=1 ORDER BY id").fetchall()
        else:
            g.accessible_schools = [school] if school else []
    else:
        g.school_id = 1
        g.current_school = None
        g.accessible_schools = []


@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


@app.errorhandler(400)
def handle_bad_request(e):
    msg = getattr(e, "description", "La requête formulée est invalide ou le jeton de sécurité a expiré.")
    return render_template("error.html", code=400, title="Requête Invalide (400)", message=msg), 400


@app.errorhandler(403)
def handle_forbidden(e):
    msg = getattr(e, "description", "Vous n'avez pas l'autorisation d'accéder à cette ressource ou cette fonctionnalité.")
    return render_template("error.html", code=403, title="Accès Refusé (403)", message=msg), 403


@app.errorhandler(404)
def handle_not_found(e):
    msg = getattr(e, "description", "La page ou la ressource que vous recherchez n'existe pas ou a été déplacée.")
    return render_template("error.html", code=404, title="Page Introuvable (404)", message=msg), 404


@app.errorhandler(500)
def handle_server_error(e):
    return render_template("error.html", code=500, title="Erreur Interne (500)", message="Une erreur inattendue est survenue. Veuillez rafraîchir la page ou réessayer ultérieurement."), 500


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    try:
        db = sqlite3.connect(DATABASE, timeout=60.0)
        try:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA busy_timeout = 60000")
        except sqlite3.OperationalError:
            pass
        db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            city TEXT DEFAULT '',
            country TEXT DEFAULT '',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            academic_year TEXT NOT NULL DEFAULT '2026-2027',
            plan TEXT NOT NULL DEFAULT 'Enterprise SaaS Pro',
            currency TEXT NOT NULL DEFAULT 'DT',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'director', 'teacher', 'parent', 'accountant', 'secretary', 'student', 'superadmin')),
            full_name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            school_id INTEGER REFERENCES schools(id) DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            level TEXT NOT NULL,
            section TEXT DEFAULT '',
            capacity INTEGER NOT NULL DEFAULT 30,
            school_year TEXT NOT NULL DEFAULT '2026-2027'
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            birth_date TEXT DEFAULT '',
            parent_name TEXT DEFAULT '',
            parent_phone TEXT DEFAULT '',
            parent_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            class_id INTEGER REFERENCES classes(id) ON DELETE RESTRICT,
            school_year TEXT NOT NULL DEFAULT '2026-2027',
            medical_notes TEXT DEFAULT '',
            photo_path TEXT DEFAULT '',
            student_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, coefficient REAL NOT NULL DEFAULT 1,
            level TEXT NOT NULL, school_year TEXT NOT NULL DEFAULT '2026-2027', active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, capacity INTEGER NOT NULL DEFAULT 30,
            availability TEXT DEFAULT '', school_year TEXT NOT NULL DEFAULT '2026-2027', active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS teacher_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, teacher_id INTEGER NOT NULL REFERENCES users(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id), class_id INTEGER NOT NULL REFERENCES classes(id),
            school_year TEXT NOT NULL DEFAULT '2026-2027', UNIQUE(teacher_id,subject_id,class_id,school_year)
        );
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT, class_id INTEGER NOT NULL REFERENCES classes(id),
            teacher_id INTEGER NOT NULL REFERENCES users(id), subject_id INTEGER NOT NULL REFERENCES subjects(id),
            room_id INTEGER REFERENCES rooms(id), weekday INTEGER NOT NULL CHECK(weekday BETWEEN 1 AND 7),
            start_time TEXT NOT NULL, end_time TEXT NOT NULL, school_year TEXT NOT NULL DEFAULT '2026-2027'
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, subject_id INTEGER NOT NULL REFERENCES subjects(id),
            class_id INTEGER NOT NULL REFERENCES classes(id), evaluation_date TEXT NOT NULL, max_score REAL NOT NULL DEFAULT 20,
            school_year TEXT NOT NULL DEFAULT '2026-2027',
            eval_type TEXT NOT NULL DEFAULT 'Devoir Surveillé',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            room_id INTEGER REFERENCES rooms(id) DEFAULT NULL,
            instructions TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, evaluation_id INTEGER NOT NULL REFERENCES evaluations(id),
            student_id INTEGER NOT NULL REFERENCES students(id), score REAL NOT NULL, comment TEXT DEFAULT '',
            UNIQUE(evaluation_id,student_id)
        );
        CREATE TABLE IF NOT EXISTS absences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES students(id),
            absence_date TEXT NOT NULL, reason TEXT DEFAULT '', justified INTEGER NOT NULL DEFAULT 0,
            school_year TEXT NOT NULL DEFAULT '2026-2027'
        );
        CREATE TABLE IF NOT EXISTS fee_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, amount REAL NOT NULL,
            due_date TEXT DEFAULT '', school_year TEXT NOT NULL DEFAULT '2026-2027'
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES students(id),
            amount REAL NOT NULL, paid_at TEXT NOT NULL, method TEXT NOT NULL, reference TEXT DEFAULT '',
            school_year TEXT NOT NULL DEFAULT '2026-2027', created_by INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT DEFAULT '',
            subject_id INTEGER NOT NULL REFERENCES subjects(id), class_id INTEGER NOT NULL REFERENCES classes(id),
            teacher_id INTEGER NOT NULL REFERENCES users(id), due_date TEXT NOT NULL, attachment_path TEXT DEFAULT '',
            correction_path TEXT DEFAULT '', school_year TEXT NOT NULL DEFAULT '2026-2027', active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, homework_id INTEGER NOT NULL REFERENCES homework(id),
            student_id INTEGER NOT NULL REFERENCES students(id), file_path TEXT NOT NULL, submitted_at TEXT NOT NULL,
            score REAL, comment TEXT DEFAULT '', UNIQUE(homework_id,student_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER NOT NULL REFERENCES users(id), subject TEXT NOT NULL, body TEXT NOT NULL,
            sent_at TEXT NOT NULL, read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL,
            audience TEXT NOT NULL DEFAULT 'all', created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
            entity TEXT NOT NULL, entity_id INTEGER, old_values TEXT DEFAULT '', new_values TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), channel TEXT NOT NULL,
            message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pre_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            birth_date TEXT DEFAULT '', parent_name TEXT NOT NULL, parent_email TEXT DEFAULT '', parent_phone TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS school_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'event',
            start_date TEXT NOT NULL,
            end_date TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            description TEXT DEFAULT '',
            audience TEXT NOT NULL DEFAULT 'all',
            school_year TEXT NOT NULL DEFAULT '2026-2027',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demo_seed (seed_key TEXT PRIMARY KEY, created_at TEXT NOT NULL);
    """)
        migrations = {
            "users": {"full_name": "TEXT DEFAULT ''", "email": "TEXT DEFAULT ''", "active": "INTEGER NOT NULL DEFAULT 1", "school_id": "INTEGER REFERENCES schools(id) DEFAULT 1"},
            "students": {"medical_notes": "TEXT DEFAULT ''", "photo_path": "TEXT DEFAULT ''", "parent_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL", "student_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL"},
            "messages": {"is_draft": "INTEGER NOT NULL DEFAULT 0", "attachment_path": "TEXT DEFAULT ''", "hidden_by_sender": "INTEGER NOT NULL DEFAULT 0", "hidden_by_recipient": "INTEGER NOT NULL DEFAULT 0"},
            "evaluations": {
                "eval_type": "TEXT DEFAULT 'Devoir Surveillé'",
                "start_time": "TEXT DEFAULT ''",
                "end_time": "TEXT DEFAULT ''",
                "room_id": "INTEGER REFERENCES rooms(id) DEFAULT NULL",
                "instructions": "TEXT DEFAULT ''",
            },
        }
        for table, columns in migrations.items():
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, declaration in columns.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        db.execute("UPDATE students SET student_user_id=NULL WHERE student_user_id IS NOT NULL AND id NOT IN (SELECT MIN(id) FROM students WHERE student_user_id IS NOT NULL GROUP BY student_user_id)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_student_user ON students(student_user_id) WHERE student_user_id IS NOT NULL")
        
        # Mettre à jour la devise en Dinar Tunisien (DT) pour toutes les écoles
        db.execute("UPDATE schools SET currency='DT'")

        now_ts = datetime.now().isoformat(timespec='seconds')
        if not db.execute("SELECT id FROM schools LIMIT 1").fetchone():
            db.execute("INSERT OR IGNORE INTO schools(id, name, code, city, country, academic_year, plan, currency, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (1, "Lycée & Collège Pilote de Tunis", "TUNIS-PILOTE", "Tunis", "Tunisie", "2026-2027", "Enterprise SaaS Pro", "DT", 1, now_ts))
            db.execute("INSERT OR IGNORE INTO schools(id, name, code, city, country, academic_year, plan, currency, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (2, "Groupe Scolaire Hannibal", "HANNIBAL", "Sousse", "Tunisie", "2026-2027", "Enterprise SaaS Pro", "DT", 1, now_ts))
            db.execute("INSERT OR IGNORE INTO schools(id, name, code, city, country, academic_year, plan, currency, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (3, "Institution Privée Ibn Khaldoun", "KHALDOUN", "Sfax", "Tunisie", "2026-2027", "Enterprise SaaS Pro", "DT", 1, now_ts))
        else:
            db.execute("UPDATE schools SET name='Lycée & Collège Pilote de Tunis', city='Tunis', country='Tunisie', currency='DT' WHERE id=1")
            db.execute("UPDATE schools SET name='Groupe Scolaire Hannibal', city='Sousse', country='Tunisie', currency='DT' WHERE id=2")
            db.execute("INSERT OR IGNORE INTO schools(id, name, code, city, country, academic_year, plan, currency, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (2, "Groupe Scolaire Hannibal", "HANNIBAL", "Sousse", "Tunisie", "2026-2027", "Enterprise SaaS Pro", "DT", 1, now_ts))
            db.execute("INSERT OR IGNORE INTO schools(id, name, code, city, country, academic_year, plan, currency, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (3, "Institution Privée Ibn Khaldoun", "KHALDOUN", "Sfax", "Tunisie", "2026-2027", "Enterprise SaaS Pro", "DT", 1, now_ts))

        if not db.execute("SELECT id FROM users LIMIT 1").fetchone():
            db.execute("INSERT INTO users(username,password_hash,role,full_name,email,school_id) VALUES(?,?,?,?,?,?)",
                       ("admin", generate_password_hash("admin123"), "admin", "Administrateur Général", "admin@educloud.tn", 1))
            db.execute("INSERT INTO users(username,password_hash,role,full_name,email,school_id) VALUES(?,?,?,?,?,?)",
                       ("comptable", generate_password_hash("compta123"), "accountant", "Sihem Mansouri", "compta@educloud.tn", 1))

        # Initialisation complète avec le jeu de données tunisien (DT)
        if not db.execute("SELECT 1 FROM demo_seed WHERE seed_key='school-demo-tunisie-dt-v1'").fetchone():
            seed_demo_data(db)
            db.execute("INSERT OR REPLACE INTO demo_seed(seed_key,created_at) VALUES(?,?)", ("school-demo-tunisie-dt-v1", datetime.now().isoformat(timespec="seconds")))

        db.commit()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "busy" in str(e).lower():
            pass
        else:
            raise
    finally:
        try:
            db.close()
        except Exception:
            pass


def seed_demo_data(db):
    """Populate database with complete, realistic demo records tailored for Tunisia (currency: DT)."""
    year = "2026-2027"
    today = datetime.now().date()
    now_min = datetime.now().isoformat(timespec="minutes")
    now_sec = datetime.now().isoformat(timespec="seconds")

    # Devise nationale en Dinar Tunisien (DT)
    db.execute("UPDATE schools SET currency='DT'")

    # 1. Utilisateurs complets pour tous les rôles
    users = [
        ("admin", "admin", "Administrateur Général", "admin@educloud.tn", "admin123", 1),
        ("directeur", "director", "Dr. Moncef Ben Salem", "direction@educloud.tn", "directeur123", 1),
        ("comptable", "accountant", "Sihem Mansouri", "compta@educloud.tn", "compta123", 1),
        ("secretaire", "secretary", "Meriem Trabelsi", "secretariat@educloud.tn", "secret123", 1),
        ("enseignant", "teacher", "Tarek Bouazizi", "prof.math@educloud.tn", "prof123", 1),
        ("prof.francais", "teacher", "Sonia Gharbi", "prof.francais@educloud.tn", "prof123", 1),
        ("prof.arabe", "teacher", "Hichem Jaziri", "prof.arabe@educloud.tn", "prof123", 1),
        ("prof.sciences", "teacher", "Nadia Ben Youssef", "prof.sciences@educloud.tn", "prof123", 1),
        ("parent", "parent", "Karim Ben Amor", "parent@example.test", "parent123", 1),
        ("parent2", "parent", "Leila Hammami", "parent2@example.test", "parent123", 1),
        ("parent3", "parent", "Mohamed Dridi", "parent3@example.test", "parent123", 1),
        ("eleve", "student", "Awa Ndiaye", "eleve@example.test", "eleve123", 1),
        ("eleve2", "student", "Cheikh Diop", "eleve2@example.test", "eleve123", 1),
        ("eleve3", "student", "Marième Sow", "eleve3@example.test", "eleve123", 1),
        ("eleve.nour", "student", "Nour Dridi", "eleve.nour@educloud.tn", "eleve123", 1),
    ]
    user_ids = {}
    for username, role, name, email, password, school_id in users:
        existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            db.execute(
                "UPDATE users SET password_hash=?, role=?, full_name=?, email=?, school_id=?, active=1 WHERE id=?",
                (generate_password_hash(password), role, name, email, school_id, existing[0])
            )
            user_ids[username] = existing[0]
        else:
            cur = db.execute(
                "INSERT INTO users(username,password_hash,role,full_name,email,school_id,active) VALUES(?,?,?,?,?,?,1)",
                (username, generate_password_hash(password), role, name, email, school_id)
            )
            user_ids[username] = cur.lastrowid

    admin_id = user_ids["admin"]
    director_id = user_ids["directeur"]
    accountant_id = user_ids["comptable"]

    # Nettoyage des anciennes données de démonstration pour réinitialisation propre
    for tbl in ["submissions", "homework", "grades", "evaluations", "timetable", "teacher_assignments",
                "absences", "payments", "fee_schedules", "students", "classes", "subjects", "rooms",
                "messages", "announcements", "notifications", "pre_enrollments"]:
        try:
            db.execute(f"DELETE FROM {tbl}")
        except Exception:
            pass

    # 2. Classes (incluant classes fondamentales et secondaires tunisiennes)
    classes_data = [
        ("CP-A", "CP", "A", 25),
        ("CE1-A", "CE1", "A", 25),
        ("CE2-A", "CE2", "A", 25),
        ("7ème Année de Base A", "7ème Base", "A", 30),
        ("8ème Année de Base B", "8ème Base", "B", 30),
        ("9ème Année Pilote", "9ème Pilote", "Pilote", 28),
        ("1ère Année Secondaire S1", "1ère Sec", "1", 32),
    ]
    classes = []
    class_map = {}
    for name, level, section, capacity in classes_data:
        cid = db.execute(
            "INSERT INTO classes(name,level,section,capacity,school_year) VALUES(?,?,?,?,?)",
            (name, level, section, capacity, year),
        ).lastrowid
        classes.append(cid)
        class_map[name] = cid
        class_map[level] = cid

    # 3. Matières & Coefficients
    subjects_spec = [
        ("Français", 2.0, "CP"),
        ("Mathématiques", 2.0, "CP"),
        ("Découverte du monde", 1.0, "CP"),
        ("Français", 2.0, "CE1"),
        ("Mathématiques", 2.0, "CE1"),
        ("Sciences", 1.0, "CE1"),
        ("Français", 2.0, "CE2"),
        ("Mathématiques", 2.0, "CE2"),
        ("Histoire-géographie", 1.0, "CE2"),
        ("Mathématiques", 3.0, "7ème Base"),
        ("Langue Arabe", 3.0, "7ème Base"),
        ("Français", 2.5, "7ème Base"),
        ("Sciences de la Vie et de la Terre", 2.0, "7ème Base"),
        ("Anglais", 1.5, "7ème Base"),
        ("Informatique & Robotique", 1.5, "7ème Base"),
        ("Mathématiques", 3.0, "9ème Pilote"),
        ("Français", 2.5, "9ème Pilote"),
        ("Langue Arabe", 3.0, "9ème Pilote"),
        ("Sciences Physiques", 2.0, "9ème Pilote"),
    ]
    subject_ids = {}
    for name, coeff, level in subjects_spec:
        sid = db.execute(
            "INSERT INTO subjects(name,coefficient,level,school_year,active) VALUES(?,?,?,?,1)",
            (name, coeff, level, year),
        ).lastrowid
        subject_ids[(level, name)] = sid

    # 4. Salles de classe & Laboratoires
    rooms_data = [
        ("Salle 1 - Ibn Rouchd", 32, "Disponible lun-sam 08h-18h"),
        ("Salle 2 - Abou El Kacem Chebbi", 30, "Disponible lun-sam 08h-18h"),
        ("Bibliothèque & Médiathèque", 40, "Espace recherche et documentation"),
        ("Laboratoire des Sciences (Lab 1)", 28, "Équipé paillasses & microscopes"),
        ("Laboratoire Informatique & IA", 30, "30 postes connectés fibre"),
    ]
    room_ids = [
        db.execute(
            "INSERT INTO rooms(name,capacity,availability,school_year,active) VALUES(?,?,?,?,1)",
            (name, cap, avail, year),
        ).lastrowid
        for name, cap, avail in rooms_data
    ]

    # 5. Élèves liés aux parents et aux comptes élèves
    sample_students = [
        ("Awa", "Ndiaye", "2019-04-12", class_map["CP-A"], user_ids["parent"], user_ids["eleve"], "+216 71 100 200"),
        ("Ibrahima", "Ndiaye", "2021-09-03", class_map["CP-A"], user_ids["parent"], None, "+216 71 100 200"),
        ("Fatou", "Ndiaye", "2020-06-19", class_map["CP-A"], user_ids["parent"], None, "+216 71 100 200"),
        ("Cheikh", "Diop", "2018-11-21", class_map["CE1-A"], user_ids["parent2"], user_ids["eleve2"], "+216 73 200 300"),
        ("Aminata", "Diop", "2019-03-07", class_map["CE1-A"], user_ids["parent2"], None, "+216 73 200 300"),
        ("Marième", "Sow", "2017-07-08", class_map["CE2-A"], user_ids["parent3"], user_ids["eleve3"], "+216 74 300 400"),
        ("Moussa", "Sow", "2018-02-14", class_map["CE2-A"], user_ids["parent3"], None, "+216 74 300 400"),
        ("Amine", "Ben Amor", "2012-05-14", class_map["7ème Base"], user_ids["parent"], None, "+216 98 123 456"),
        ("Sarra", "Ben Amor", "2014-08-22", class_map["7ème Base"], user_ids["parent"], None, "+216 98 123 456"),
        ("Yassine", "Hammami", "2011-11-03", class_map["9ème Pilote"], user_ids["parent2"], None, "+216 22 987 654"),
        ("Nour", "Dridi", "2011-03-18", class_map["9ème Pilote"], user_ids["parent3"], user_ids["eleve.nour"], "+216 55 456 789"),
    ]
    students = []
    for first, last, birth, cid, pid, suid, phone in sample_students:
        pname = db.execute("SELECT full_name FROM users WHERE id=?", (pid,)).fetchone()[0]
        sid = db.execute(
            "INSERT INTO students(first_name,last_name,birth_date,parent_name,parent_phone,parent_user_id,class_id,school_year,student_user_id,medical_notes,active) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
            (first, last, birth, pname, phone, pid, cid, year, suid, "R.A.S. - Dossier médical complet"),
        ).lastrowid
        students.append((sid, cid, first, last))

    # 6. Affectations Enseignants & Emploi du temps
    assignments = [
        (user_ids["enseignant"], subject_ids[("CP", "Français")], class_map["CP-A"]),
        (user_ids["enseignant"], subject_ids[("CP", "Mathématiques")], class_map["CP-A"]),
        (user_ids["enseignant"], subject_ids[("CE1", "Français")], class_map["CE1-A"]),
        (user_ids["enseignant"], subject_ids[("CE2", "Français")], class_map["CE2-A"]),
        (user_ids["enseignant"], subject_ids[("7ème Base", "Mathématiques")], class_map["7ème Base"]),
        (user_ids["prof.francais"], subject_ids[("7ème Base", "Français")], class_map["7ème Base"]),
        (user_ids["prof.arabe"], subject_ids[("7ème Base", "Langue Arabe")], class_map["7ème Base"]),
        (user_ids["prof.sciences"], subject_ids[("7ème Base", "Sciences de la Vie et de la Terre")], class_map["7ème Base"]),
        (user_ids["enseignant"], subject_ids[("9ème Pilote", "Mathématiques")], class_map["9ème Pilote"]),
        (user_ids["prof.francais"], subject_ids[("9ème Pilote", "Français")], class_map["9ème Pilote"]),
    ]
    for tid, subid, cid in assignments:
        db.execute(
            "INSERT OR IGNORE INTO teacher_assignments(teacher_id,subject_id,class_id,school_year) VALUES(?,?,?,?)",
            (tid, subid, cid, year),
        )

    # Emploi du temps
    tt_slots = [
        (class_map["CP-A"], user_ids["enseignant"], subject_ids[("CP", "Français")], room_ids[0], 1, "08:00", "09:00"),
        (class_map["CE1-A"], user_ids["enseignant"], subject_ids[("CE1", "Français")], room_ids[1], 2, "08:00", "09:00"),
        (class_map["CE2-A"], user_ids["enseignant"], subject_ids[("CE2", "Français")], room_ids[2], 3, "08:00", "09:00"),
        (class_map["7ème Base"], user_ids["enseignant"], subject_ids[("7ème Base", "Mathématiques")], room_ids[0], 1, "09:15", "10:45"),
        (class_map["7ème Base"], user_ids["prof.francais"], subject_ids[("7ème Base", "Français")], room_ids[1], 2, "10:15", "11:45"),
        (class_map["9ème Pilote"], user_ids["enseignant"], subject_ids[("9ème Pilote", "Mathématiques")], room_ids[0], 4, "10:15", "12:15"),
    ]
    for cid, tid, subid, rid, wday, stime, etime in tt_slots:
        db.execute(
            "INSERT INTO timetable(class_id,teacher_id,subject_id,room_id,weekday,start_time,end_time,school_year) VALUES(?,?,?,?,?,?,?,?)",
            (cid, tid, subid, rid, wday, stime, etime, year),
        )

    # 7. Évaluations & Notes (Échelle 0-20)
    ev_cp = db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Évaluation de français - période 1", subject_ids[("CP", "Français")], class_map["CP-A"], (today - timedelta(days=2)).isoformat(), 20, year, "Contrôle Continu", "08:30", "09:30", room_ids[0], "Dictée et lecture suivie."),
    ).lastrowid
    ev_ce1 = db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Évaluation de français - période 1", subject_ids[("CE1", "Français")], class_map["CE1-A"], (today - timedelta(days=2)).isoformat(), 20, year, "Contrôle Continu", "08:30", "09:30", room_ids[1], "Grammaire et conjugaison."),
    ).lastrowid
    ev_ce2 = db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Évaluation de français - période 1", subject_ids[("CE2", "Français")], class_map["CE2-A"], (today - timedelta(days=2)).isoformat(), 20, year, "Contrôle Continu", "08:30", "09:30", room_ids[2], "Vocabulaire et compréhension."),
    ).lastrowid
    ev_math = db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Devoir de Contrôle N°1 - Algèbre & Géométrie", subject_ids[("7ème Base", "Mathématiques")], class_map["7ème Base"], (today - timedelta(days=5)).isoformat(), 20, year, "Devoir Surveillé", "09:15", "10:45", room_ids[0], "Algèbre, calcul littéral et théorème de Thalès."),
    ).lastrowid
    ev_math_pilote = db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Olympiade & Contrôle Pilote N°1", subject_ids[("9ème Pilote", "Mathématiques")], class_map["9ème Pilote"], (today - timedelta(days=4)).isoformat(), 20, year, "Devoir Surveillé", "10:15", "12:15", room_ids[0], "Niveau concours d'excellence."),
    ).lastrowid

    # Évaluations à venir (Devoirs surveillés & Synthèses planifiés)
    db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Devoir Surveillé N°2 - Calcul & Équations", subject_ids[("7ème Base", "Mathématiques")], class_map["7ème Base"], (today + timedelta(days=4)).isoformat(), 20, year, "Devoir Surveillé", "08:30", "10:30", room_ids[0], "Chapitres 3 et 4 du manuel officiel. Calculatrice non autorisée."),
    )
    db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Devoir de Synthèse N°1 - Expression Écrite", subject_ids[("7ème Base", "Français")], class_map["7ème Base"], (today + timedelta(days=8)).isoformat(), 20, year, "Devoir de Synthèse", "10:00", "12:00", room_ids[1], "Production écrite argumentative et analyse stylistique."),
    )
    db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Examen Blanc - Session Pilote", subject_ids[("9ème Pilote", "Mathématiques")], class_map["9ème Pilote"], (today + timedelta(days=12)).isoformat(), 20, year, "Examen Blanc", "08:00", "11:00", room_ids[0], "Simulateur d'épreuve du concours d'accès aux lycées pilotes."),
    )
    db.execute(
        "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year,eval_type,start_time,end_time,room_id,instructions) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("Oral de Synthèse - Éloquence & Débat", subject_ids[("9ème Pilote", "Français")], class_map["9ème Pilote"], (today + timedelta(days=15)).isoformat(), 20, year, "Oral de Synthèse", "14:00", "16:00", room_ids[2], "Exposé oral de 10 min suivi de 5 min de questions du jury."),
    )

    grades_data = [
        (ev_cp, students[0][0], 15.5, "Très bon travail."),
        (ev_cp, students[1][0], 14.0, "Bon début d'année."),
        (ev_ce1, students[3][0], 15.5, "Très bon travail."),
        (ev_ce2, students[5][0], 15.5, "Très bon travail."),
        (ev_math, students[7][0], 18.5, "Excellent raisonnement mathématique."),
        (ev_math, students[8][0], 15.0, "Bonne rigueur de calcul."),
        (ev_math_pilote, students[9][0], 19.0, "Performance de niveau concours."),
        (ev_math_pilote, students[10][0], 17.5, "Excellente analyse géométrique."),
    ]
    for evid, stid, score, comment in grades_data:
        db.execute("INSERT OR REPLACE INTO grades(evaluation_id,student_id,score,comment) VALUES(?,?,?,?)",
                   (evid, stid, score, comment))

    # 8. Devoirs à la maison & Soumissions (due_date > today)
    hw_cp = db.execute(
        "INSERT INTO homework(title,description,subject_id,class_id,teacher_id,due_date,school_year,active) VALUES(?,?,?,?,?,?,?,1)",
        ("Lecture de la semaine", "Lire un texte et préparer un résumé oral.", subject_ids[("CP", "Français")], class_map["CP-A"], user_ids["enseignant"], (today + timedelta(days=7)).isoformat(), year),
    ).lastrowid
    hw_math = db.execute(
        "INSERT INTO homework(title,description,subject_id,class_id,teacher_id,due_date,school_year,active) VALUES(?,?,?,?,?,?,?,1)",
        ("Problème d'arithmétique N°2", "Résoudre les exercices 4, 5 et 6 page 42 du manuel scolaire tunisien.", subject_ids[("7ème Base", "Mathématiques")], class_map["7ème Base"], user_ids["enseignant"], (today + timedelta(days=5)).isoformat(), year),
    ).lastrowid

    # Soumissions d'élèves
    db.execute(
        "INSERT OR REPLACE INTO submissions(homework_id,student_id,file_path,submitted_at,score,comment) VALUES(?,?,?,?,?,?)",
        (hw_math, students[7][0], "uploads/homework/devoir_amine_benamor.pdf", (today - timedelta(days=1)).isoformat() + " 18:30", 19.0, "Devoir parfaitement rédigé et soigné."),
    )
    db.execute(
        "INSERT OR REPLACE INTO submissions(homework_id,student_id,file_path,submitted_at,score,comment) VALUES(?,?,?,?,?,?)",
        (hw_math, students[8][0], "uploads/homework/devoir_sarra_benamor.pdf", today.isoformat() + " 10:15", 16.5, "Très bonne copie."),
    )

    # 9. Assiduité & Absences (absence_date <= today)
    db.execute("INSERT INTO absences(student_id,absence_date,reason,justified,school_year) VALUES(?,?,?,?,?)",
               (students[0][0], (today - timedelta(days=2)).isoformat(), "Rendez-vous médical", 1, year))
    db.execute("INSERT INTO absences(student_id,absence_date,reason,justified,school_year) VALUES(?,?,?,?,?)",
               (students[4][0], (today - timedelta(days=1)).isoformat(), "Absence imprévue - justificatif en attente", 0, year))
    db.execute("INSERT INTO absences(student_id,absence_date,reason,justified,school_year) VALUES(?,?,?,?,?)",
               (students[9][0], (today - timedelta(days=4)).isoformat(), "Participation aux Olympiades régionales de Mathématiques", 1, year))

    # 10. Échéancier de frais scolaires en Dinars Tunisiens (DT)
    fees_schedule = [
        ("Frais d'inscription & Assurance annuelle", 250.0, 15),
        ("Frais de scolarité - Trimestre 1", 650.0, 30),
        ("Frais de scolarité - Trimestre 2", 650.0, 90),
        ("Frais de scolarité - Trimestre 3", 650.0, 180),
        ("Abonnement Cantine & Restauration", 350.0, 30),
        ("Club Robotique & Intelligence Artificielle", 120.0, 45),
    ]
    for label, amount, days in fees_schedule:
        db.execute(
            "INSERT INTO fee_schedules(label,amount,due_date,school_year) VALUES(?,?,?,?)",
            (label, amount, (today + timedelta(days=days)).isoformat(), year),
        )

    # 11. Paiements encaissés en Dinars Tunisiens (DT)
    # Exactement 6 paiements avec référence 'DEMO-%' pour compatibilité des tests d'idempotence
    demo_payments = [
        (students[0][0], 250.0, (today - timedelta(days=1)).isoformat(), "Mobile money", "DEMO-001"),
        (students[1][0], 650.0, (today - timedelta(days=2)).isoformat(), "Espèces", "DEMO-002"),
        (students[2][0], 250.0, (today - timedelta(days=3)).isoformat(), "Mobile money", "DEMO-003"),
        (students[3][0], 650.0, (today - timedelta(days=4)).isoformat(), "Espèces", "DEMO-004"),
        (students[4][0], 350.0, (today - timedelta(days=5)).isoformat(), "Mobile money", "DEMO-005"),
        (students[5][0], 650.0, (today - timedelta(days=6)).isoformat(), "Espèces", "DEMO-006"),
    ]
    for stid, amount, pdate, method, ref in demo_payments:
        db.execute(
            "INSERT INTO payments(student_id,amount,paid_at,method,reference,school_year,created_by) VALUES(?,?,?,?,?,?,?)",
            (stid, amount, pdate, method, ref, year, accountant_id),
        )

    # Paiements tunisiens complémentaires
    extra_payments = [
        (students[7][0], 900.0, (today - timedelta(days=15)).isoformat(), "Virement bancaire", "VIR-BIAT-2026-081", accountant_id),
        (students[9][0], 650.0, (today - timedelta(days=8)).isoformat(), "Flouci / e-Dinar", "PAY-FLOUCI-55410", accountant_id),
        (students[10][0], 900.0, (today - timedelta(days=10)).isoformat(), "Virement bancaire", "VIR-BNA-88741", accountant_id),
    ]
    for stid, amount, pdate, method, ref, cby in extra_payments:
        db.execute(
            "INSERT INTO payments(student_id,amount,paid_at,method,reference,school_year,created_by) VALUES(?,?,?,?,?,?,?)",
            (stid, amount, pdate, method, ref, year, cby),
        )

    # 12. Messagerie interne
    messages_data = [
        (user_ids["enseignant"], user_ids["parent"], "Suivi scolaire d’Awa",
         "Awa participe bien en classe. Pensez à vérifier son devoir de lecture et encourager ses progrès.",
         (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes")),
        (user_ids["directeur"], user_ids["enseignant"], "Coordination pédagogique du 1er trimestre",
         "Chers professeurs, nous tiendrons le conseil de coordination ce jeudi à 16h30 en salle Ibn Rouchd. Merci de préparer les fiches de synthèse.",
         (datetime.now() - timedelta(days=2)).isoformat(timespec="minutes")),
        (user_ids["comptable"], user_ids["parent"], "Confirmation de réception du règlement (Trimestre 1)",
         "Madame, Monsieur, nous accusons bonne réception de votre virement de 900 DT pour l'inscription et le 1er trimestre. Le reçu officiel est téléchargeable.",
         (datetime.now() - timedelta(days=4)).isoformat(timespec="minutes")),
    ]
    for snd, rcv, subj, body, sat in messages_data:
        db.execute(
            "INSERT INTO messages(sender_id,recipient_id,subject,body,sent_at) VALUES(?,?,?,?,?)",
            (snd, rcv, subj, body, sat),
        )

    # 13. Annonces & Actualités officielles
    announcements_data = [
        ("Bienvenue pour la rentrée 2026-2027",
         "Les cours ont repris. Consultez l’emploi du temps et les informations de classe dans votre espace en ligne.",
         "all", director_id),
        ("Ouverture des inscriptions aux clubs d'excellence (Robotique & Débat)",
         "Les ateliers scientifiques de robotique, d'intelligence artificielle et d'éloquence débuteront le samedi prochain. Inscriptions ouvertes auprès du secrétariat.",
         "all", director_id),
        ("Réunion générale des parents d'élèves",
         "La première rencontre parents-professeurs aura lieu ce samedi à 10h00 dans l'amphithéâtre Chebbi. Votre présence est vivement souhaitée.",
         "parents", admin_id),
    ]
    for title, body, aud, cby in announcements_data:
        db.execute(
            "INSERT INTO announcements(title,body,audience,created_by,created_at) VALUES(?,?,?,?,?)",
            (title, body, aud, cby, now_min),
        )

    # 14. Notifications
    notifs = [
        (user_ids["parent"], "internal", "Un nouveau devoir de lecture est disponible.", "queued"),
        (user_ids["parent"], "internal", "Une nouvelle note de Mathématiques (18.5/20) est enregistrée pour Amine.", "delivered"),
        (user_ids["parent2"], "internal", "Reçu de paiement émis : 650 DT (Flouci / e-Dinar).", "delivered"),
        (user_ids["eleve"], "internal", "Votre travail sur l'arithmétique a été noté : 19/20 avec félicitations.", "delivered"),
    ]
    for uid, ch, msg, st in notifs:
        db.execute(
            "INSERT INTO notifications(user_id,channel,message,status,created_at) VALUES(?,?,?,?,?)",
            (uid, ch, msg, st, now_min),
        )

    # 15. Préinscriptions pour la session à venir
    pre_enrolls = [
        ("Kais", "Mabrouk", "2013-04-10", "Faouzi Mabrouk", "faouzi.mabrouk@gnet.tn", "+216 23 888 999", "pending"),
        ("Salma", "Belhadj", "2012-10-05", "Ines Belhadj", "ines.belhadj@topnet.tn", "+216 97 444 333", "approved"),
        ("Ahmed", "Khemir", "2014-01-15", "Tahar Khemir", "tahar.khemir@gmail.com", "+216 50 111 222", "pending"),
    ]
    for fn, ln, bd, pn, pe, pp, st in pre_enrolls:
        db.execute(
            "INSERT INTO pre_enrollments(first_name,last_name,birth_date,parent_name,parent_email,parent_phone,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (fn, ln, bd, pn, pe, pp, st, now_min),
        )

    # 15b. Événements scolaires du calendrier
    school_events_data = [
        ("Conseil Pédagogique du 1er Trimestre", "meeting", (today + timedelta(days=3)).isoformat(), (today + timedelta(days=3)).isoformat(), "15:30", "17:30", "Harmonisation des barèmes et suivi des progressions pédagogiques.", "teachers"),
        ("Rencontre Parents - Professeurs", "meeting", (today + timedelta(days=6)).isoformat(), (today + timedelta(days=6)).isoformat(), "09:00", "13:00", "Échanges individuels sur les résultats et l'adaptation des élèves.", "all"),
        ("Journée Portes Ouvertes & Exposition Robotique", "event", (today + timedelta(days=14)).isoformat(), (today + timedelta(days=14)).isoformat(), "10:00", "16:00", "Démonstration des robots et projets scientifiques conçus par les collégiens.", "all"),
        ("Session des Devoirs de Synthèse Trimestriels", "exam", (today + timedelta(days=20)).isoformat(), (today + timedelta(days=25)).isoformat(), "08:00", "12:30", "Semaine bloquée pour les devoirs de synthèse de toutes les matières.", "all"),
    ]
    for se_title, se_type, se_start, se_end, se_stime, se_etime, se_desc, se_aud in school_events_data:
        db.execute(
            "INSERT INTO school_events(title,event_type,start_date,end_date,start_time,end_time,description,audience,school_year,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (se_title, se_type, se_start, se_end, se_stime, se_etime, se_desc, se_aud, year, admin_id, now_sec),
        )

    # 16. Journal d'audit initial
    db.execute(
        "INSERT INTO audit_log(user_id,action,entity,entity_id,old_values,new_values,created_at) VALUES(?,?,?,?,?,?,?)",
        (admin_id, "SEED_INIT", "system", 1, "", "Données de démonstration Tunisie (DT) initialisées avec succès", now_sec),
    )

    db.execute("INSERT OR REPLACE INTO demo_seed(seed_key,created_at) VALUES(?,?)", ("school-demo-tunisie-dt-v1", now_sec))


def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id=session.get("user_id")
            if not user_id:
                return redirect(url_for("login", next=request.path))
            user=get_db().execute("SELECT username,role FROM users WHERE id=? AND active=1",(user_id,)).fetchone()
            if not user:
                session.clear()
                return redirect(url_for("login"))
            session["username"]=user["username"]
            session["role"]=user["role"]
            if roles:
                eff = set(roles)
                if "admin" in eff:
                    eff.add("director")
                if user["role"] not in eff and user["role"] != "superadmin":
                    abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can_message(sender_id, sender_role, recipient_id):
    db=get_db()
    recipient=db.execute("SELECT role FROM users WHERE id=? AND active=1",(recipient_id,)).fetchone()
    if not recipient or sender_id==recipient_id:
        return False
    recipient_role=recipient["role"]
    if sender_role=="admin":
        return True
    if sender_role=="teacher":
        return recipient_role in ("admin","secretary") or (recipient_role=="parent" and bool(db.execute("SELECT 1 FROM students st JOIN teacher_assignments a ON a.class_id=st.class_id WHERE st.parent_user_id=? AND a.teacher_id=?",(recipient_id,sender_id)).fetchone()))
    if sender_role=="parent":
        return recipient_role in ("admin","secretary") or (recipient_role=="teacher" and bool(db.execute("SELECT 1 FROM students st JOIN teacher_assignments a ON a.class_id=st.class_id WHERE st.parent_user_id=? AND a.teacher_id=?",(sender_id,recipient_id)).fetchone()))
    if sender_role=="student":
        return recipient_role in ("admin","secretary","teacher") and (recipient_role in ("admin","secretary") or bool(db.execute("SELECT 1 FROM students st JOIN teacher_assignments a ON a.class_id=st.class_id WHERE st.student_user_id=? AND a.teacher_id=?",(sender_id,recipient_id)).fetchone()))
    if sender_role=="accountant":
        return recipient_role in ("admin","secretary") or (recipient_role=="parent" and bool(db.execute("SELECT 1 FROM students WHERE parent_user_id=?",(recipient_id,)).fetchone()))
    if sender_role=="secretary":
        return recipient_role in ("admin","parent")
    return False


def public_schools():
    return get_db().execute(
        "SELECT id, name, city, country FROM schools WHERE active=1 ORDER BY id"
    ).fetchall()


def find_active_user(identifier):
    ident = (identifier or "").strip()
    if not ident:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE active=1 AND (username=? OR (email != '' AND lower(email)=lower(?)))",
        (ident, ident),
    ).fetchone()


def start_user_session(user, remember=False):
    session.clear()
    session.permanent = bool(remember)
    school_id = 1
    if "school_id" in user.keys() and user["school_id"]:
        school_id = user["school_id"]
    session.update(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        school_id=school_id,
    )


def notify_admins(message):
    db = get_db()
    now = datetime.now().isoformat(timespec="minutes")
    admins = db.execute(
        "SELECT id FROM users WHERE active=1 AND role IN ('admin','director','superadmin')"
    ).fetchall()
    for admin in admins:
        db.execute(
            "INSERT INTO notifications(user_id,channel,message,status,created_at) VALUES(?,?,?,?,?)",
            (admin["id"], "internal", message, "queued", now),
        )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = find_active_user(identifier)
        if user and check_password_hash(user["password_hash"], password):
            start_user_session(user, remember=bool(request.form.get("remember_me")))
            next_url = request.args.get("next") or request.form.get("next") or ""
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("Identifiant ou mot de passe incorrect. Vérifiez vos informations ou créez un compte.", "danger")
    return render_template("login.html", schools=public_schools())


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    schools = public_schools()
    form = {
        "full_name": "",
        "username": "",
        "email": "",
        "role": "parent",
        "school_id": str(schools[0]["id"]) if schools else "1",
    }
    if request.method == "POST":
        form["full_name"] = request.form.get("full_name", "").strip()
        form["username"] = request.form.get("username", "").strip()
        form["email"] = request.form.get("email", "").strip()
        form["role"] = request.form.get("role", "parent").strip()
        form["school_id"] = request.form.get("school_id", form["school_id"]).strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        db = get_db()
        school = db.execute("SELECT id FROM schools WHERE id=? AND active=1", (form["school_id"],)).fetchone()
        if not form["full_name"] or len(form["full_name"]) < 3:
            flash("Indiquez votre nom complet (3 caractères minimum).", "danger")
        elif not USERNAME_PATTERN.match(form["username"]):
            flash("L’identifiant doit contenir 3 à 40 caractères (lettres, chiffres, point, tiret ou underscore).", "danger")
        elif form["email"] and not EMAIL_PATTERN.match(form["email"]):
            flash("L’adresse e-mail n’est pas valide.", "danger")
        elif form["role"] not in PUBLIC_REGISTER_ROLES:
            flash("Le profil choisi n’est pas autorisé pour une inscription en ligne.", "danger")
        elif not school:
            flash("Sélectionnez un établissement valide.", "danger")
        elif len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
        elif password != confirm:
            flash("La confirmation du mot de passe ne correspond pas.", "danger")
        elif db.execute(
            "SELECT 1 FROM users WHERE lower(username)=lower(?) OR (? != '' AND email != '' AND lower(email)=lower(?))",
            (form["username"], form["email"], form["email"]),
        ).fetchone():
            flash("Cet identifiant ou cet e-mail est déjà utilisé. Connectez-vous ou choisissez une autre valeur.", "danger")
        else:
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role,full_name,email,active,school_id) VALUES(?,?,?,?,?,1,?)",
                (
                    form["username"],
                    generate_password_hash(password),
                    form["role"],
                    form["full_name"],
                    form["email"],
                    school["id"],
                ),
            )
            new_id = cursor.lastrowid
            if form["role"] == "student":
                parts = form["full_name"].split(None, 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else parts[0]
                db.execute(
                    "INSERT INTO students(first_name,last_name,parent_name,student_user_id,school_year) VALUES(?,?,?,?,?)",
                    (first_name, last_name, "", new_id, "2026-2027"),
                )
            audit(
                "create",
                "user",
                new_id,
                new_values={"username": form["username"], "role": form["role"], "school_id": school["id"]},
            )
            notify_admins(
                f"Nouveau compte {form['role']} créé : {form['full_name']} ({form['username']})."
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id=?", (new_id,)).fetchone()
            start_user_session(user)
            flash("Compte créé avec succès. Bienvenue sur EduCloud.", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html", schools=schools, form=form, roles=PUBLIC_REGISTER_ROLES)


@app.route("/logout", methods=["POST"])
@login_required()
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def dashboard():
    db = get_db()
    role = session.get("role")
    user_id = session.get("user_id")

    if role == "parent":
        totals = {
            "students": db.execute("SELECT COUNT(*) FROM students WHERE active=1 AND parent_user_id=?", (user_id,)).fetchone()[0],
            "classes": db.execute("SELECT COUNT(DISTINCT class_id) FROM students WHERE active=1 AND parent_user_id=?", (user_id,)).fetchone()[0],
            "teachers": db.execute("SELECT COUNT(DISTINCT ta.teacher_id) FROM students s JOIN teacher_assignments ta ON ta.class_id=s.class_id WHERE s.active=1 AND s.parent_user_id=?", (user_id,)).fetchone()[0],
            "homework_due": db.execute("SELECT COUNT(*) FROM homework h JOIN students s ON s.class_id=h.class_id WHERE s.parent_user_id=? AND h.active=1 AND h.due_date >= date('now')", (user_id,)).fetchone()[0],
            "absences": db.execute("SELECT COUNT(*) FROM absences a JOIN students s ON s.id=a.student_id WHERE s.parent_user_id=?", (user_id,)).fetchone()[0],
        }
        recent = db.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.parent_user_id=? ORDER BY s.id DESC", (user_id,)).fetchall()

    elif role == "student":
        student_rec = db.execute("SELECT * FROM students WHERE student_user_id=? AND active=1", (user_id,)).fetchone()
        class_id = student_rec["class_id"] if student_rec else None
        totals = {
            "students": 1 if student_rec else 0,
            "classes": 1 if class_id else 0,
            "teachers": db.execute("SELECT COUNT(DISTINCT teacher_id) FROM teacher_assignments WHERE class_id=?", (class_id,)).fetchone()[0] if class_id else 0,
            "homework_due": db.execute("SELECT COUNT(*) FROM homework WHERE class_id=? AND active=1 AND due_date >= date('now')", (class_id,)).fetchone()[0] if class_id else 0,
            "grades_count": db.execute("SELECT COUNT(*) FROM grades WHERE student_id=?", (student_rec["id"],)).fetchone()[0] if student_rec else 0,
            "absences": db.execute("SELECT COUNT(*) FROM absences WHERE student_id=?", (student_rec["id"],)).fetchone()[0] if student_rec else 0,
        }
        recent = [student_rec] if student_rec else []

    elif role == "teacher":
        totals = {
            "students": db.execute("SELECT COUNT(*) FROM students WHERE active=1 AND class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)", (user_id,)).fetchone()[0],
            "classes": db.execute("SELECT COUNT(DISTINCT class_id) FROM teacher_assignments WHERE teacher_id=?", (user_id,)).fetchone()[0],
            "teachers": 1,
            "homework_active": db.execute("SELECT COUNT(*) FROM homework WHERE teacher_id=? AND active=1", (user_id,)).fetchone()[0],
            "evaluations_count": db.execute("SELECT COUNT(*) FROM evaluations WHERE class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)", (user_id,)).fetchone()[0],
        }
        recent = db.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY s.id DESC LIMIT 5", (user_id,)).fetchall()

    elif role == "accountant":
        due_total = db.execute("SELECT COALESCE(SUM(amount), 0) FROM fee_schedules WHERE school_year='2026-2027'").fetchone()[0]
        paid_total = db.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE school_year='2026-2027'").fetchone()[0]
        students_count = db.execute("SELECT COUNT(*) FROM students WHERE active=1").fetchone()[0]
        totals = {
            "students": students_count,
            "classes": db.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
            "teachers": 0,
            "paid_total": paid_total,
            "due_total": due_total * students_count,
            "payments_count": db.execute("SELECT COUNT(*) FROM payments").fetchone()[0],
        }
        recent = db.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 ORDER BY s.id DESC LIMIT 5").fetchall()

    else:
        # Admin / Director / Secretary
        totals = {
            "students": db.execute("SELECT COUNT(*) FROM students WHERE active=1").fetchone()[0],
            "classes": db.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
            "teachers": db.execute("SELECT COUNT(*) FROM users WHERE role='teacher' AND active=1").fetchone()[0],
            "pre_enrollments": db.execute("SELECT COUNT(*) FROM pre_enrollments WHERE status='pending'").fetchone()[0],
        }
        recent = db.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 ORDER BY s.id DESC LIMIT 5").fetchall()

    return render_template("dashboard.html", totals=totals, recent=recent)


@app.route("/bi")
@login_required("admin", "director", "superadmin")
def bi_hub():
    import bi_analytics as bi
    db = get_db()
    school_id = g.get("school_id") or session.get("school_id") or 1
    d1 = bi.get_dashboard_1_general(db, school_id)
    d2 = bi.get_dashboard_2_financial(db, school_id)
    d3 = bi.get_dashboard_3_pedagogical(db, school_id)
    d4 = bi.get_dashboard_4_absences(db, school_id)
    d5 = bi.get_dashboard_5_hr(db, school_id)
    d6 = bi.get_dashboard_6_enrollment(db, school_id)
    d7 = bi.get_dashboard_7_communication(db, school_id)
    d8 = bi.get_dashboard_8_resources(db, school_id)
    d9 = bi.get_dashboard_9_early_warning(db, school_id)
    d10 = bi.get_dashboard_10_strategic(db, school_id)
    return render_template("bi_hub.html", d1=d1, d2=d2, d3=d3, d4=d4, d5=d5, d6=d6, d7=d7, d8=d8, d9=d9, d10=d10)


@app.route("/bi/dashboard/<int:dash_id>")
@login_required("admin", "director", "superadmin")
def bi_dashboard(dash_id):
    return redirect(url_for("bi_hub") + f"#tab{dash_id}")


@app.route("/schools/switch/<int:school_id>")
@login_required("admin", "director", "superadmin")
def switch_school(school_id):
    db = get_db()
    school = db.execute("SELECT id, name FROM schools WHERE id=? AND active=1", (school_id,)).fetchone()
    if not school:
        flash("Établissement introuvable.", "danger")
    else:
        session["school_id"] = school["id"]
        flash(f"Établissement actif : {school['name']}", "info")
    return redirect(request.referrer or url_for("bi_hub"))


@app.route("/students")
@login_required("admin", "teacher", "accountant", "secretary", "parent", "student")
def students():
    db=get_db()
    if session.get("role") == "parent":
        rows=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.parent_user_id=? ORDER BY s.last_name,s.first_name",(session["user_id"],)).fetchall()
    elif session.get("role") == "student":
        rows=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.student_user_id=?",(session["user_id"],)).fetchall()
    elif session.get("role") == "teacher":
        rows=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY s.last_name,s.first_name",(session["user_id"],)).fetchall()
    else:
        rows=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 ORDER BY s.last_name,s.first_name").fetchall()
    return render_template("students.html", students=rows)


@app.route("/students/new", methods=["GET", "POST"])
@login_required("admin", "secretary")
def student_new():
    db = get_db()
    classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()
    parents = db.execute("SELECT id,full_name,username FROM users WHERE role='parent' AND active=1 ORDER BY username").fetchall()
    student_users = db.execute("SELECT id,full_name,username FROM users WHERE role='student' AND active=1 ORDER BY username").fetchall()
    if request.method == "POST":
        first, last = request.form.get("first_name", "").strip(), request.form.get("last_name", "").strip()
        birth_date = request.form.get("birth_date", "").strip()
        if not first or not last:
            flash("Le prénom et le nom sont obligatoires.", "danger")
        elif not is_valid_birth_date(birth_date):
            flash("La date de naissance doit être valide et ne peut pas être dans le futur.", "danger")
        else:
            class_id = request.form.get("class_id") or None
            school_year=request.form.get("school_year", "2026-2027").strip()
            parent_user_id=request.form.get("parent_user_id") or None
            student_user_id=request.form.get("student_user_id") or None
            valid_parent=not parent_user_id or db.execute("SELECT 1 FROM users WHERE id=? AND role='parent' AND active=1",(parent_user_id,)).fetchone()
            valid_student=student_account_available(student_user_id)
            if not valid_parent or not valid_student:
                flash("Les comptes associés doivent être des comptes parent ou élève actifs.","danger")
                return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=None)
            if class_id:
                room = db.execute("SELECT capacity,school_year,(SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1) AS count FROM classes WHERE id=?", (class_id, school_year, class_id)).fetchone()
                if not room or room["school_year"] != school_year or room["count"] >= room["capacity"]:
                    flash("Classe introuvable ou capacité maximale atteinte.", "danger")
                    return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=None)
            photo_path = ""
            if "photo" in request.files:
                try:
                    photo_path = save_upload(request.files.get("photo"))
                except ValueError as e:
                    flash(str(e), "danger")
                    return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=None)
            medical_notes = request.form.get("medical_notes", "").strip()
            db.execute("INSERT INTO students(first_name,last_name,birth_date,parent_name,parent_phone,parent_user_id,student_user_id,class_id,school_year,medical_notes,photo_path) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (first, last, birth_date, request.form.get("parent_name", "").strip(), request.form.get("parent_phone", "").strip(), parent_user_id, student_user_id, class_id, school_year, medical_notes, photo_path))
            new_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit("create","student",new_id,new_values={"first_name":first,"last_name":last,"class_id":class_id})
            db.commit()
            flash("Élève ajouté avec succès.", "success")
            return redirect(url_for("students"))
    return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=None)


@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required("admin", "secretary")
def student_edit(student_id):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id=? AND active=1", (student_id,)).fetchone()
    if not student:
        abort(404)
    classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()
    parents = db.execute("SELECT id,full_name,username FROM users WHERE role='parent' AND active=1 ORDER BY username").fetchall()
    student_users = db.execute("SELECT id,full_name,username FROM users WHERE role='student' AND active=1 ORDER BY username").fetchall()
    if request.method == "POST":
        first, last = request.form.get("first_name", "").strip(), request.form.get("last_name", "").strip()
        birth_date = request.form.get("birth_date", "").strip()
        if not first or not last:
            flash("Le prénom et le nom sont obligatoires.", "danger")
        elif not is_valid_birth_date(birth_date):
            flash("La date de naissance doit être valide et ne peut pas être dans le futur.", "danger")
        else:
            class_id=request.form.get("class_id") or None
            school_year=request.form.get("school_year", "2026-2027").strip()
            parent_user_id=request.form.get("parent_user_id") or None
            student_user_id=request.form.get("student_user_id") or None
            valid_parent=not parent_user_id or db.execute("SELECT 1 FROM users WHERE id=? AND role='parent' AND active=1",(parent_user_id,)).fetchone()
            valid_student=student_account_available(student_user_id,student_id)
            if not valid_parent or not valid_student:
                flash("Les comptes associés doivent être des comptes parent ou élève actifs.","danger")
                return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=student)
            if class_id:
                room=db.execute("SELECT capacity,school_year,(SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1 AND id<>?) AS count FROM classes WHERE id=?",(class_id,school_year,student_id,class_id)).fetchone()
                if not room or room["school_year"]!=school_year or room["count"]>=room["capacity"]:
                    flash("Classe invalide ou capacité maximale atteinte pour cette année scolaire.","danger")
                    return render_template("student_form.html",classes=classes,parents=parents,student_users=student_users,student=student)
            old_values={"first_name":student["first_name"],"last_name":student["last_name"],"class_id":student["class_id"]}
            photo_path = student["photo_path"]
            if "photo" in request.files and request.files.get("photo").filename:
                try:
                    photo_path = save_upload(request.files.get("photo"))
                except ValueError as e:
                    flash(str(e), "danger")
                    return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=student)
            medical_notes = request.form.get("medical_notes", "").strip()
            db.execute("UPDATE students SET first_name=?,last_name=?,birth_date=?,parent_name=?,parent_phone=?,parent_user_id=?,student_user_id=?,class_id=?,school_year=?,medical_notes=?,photo_path=? WHERE id=?",
                       (first,last,birth_date,request.form.get("parent_name", "").strip(),request.form.get("parent_phone", "").strip(),parent_user_id,student_user_id,class_id,school_year,medical_notes,photo_path,student_id))
            audit("update","student",student_id,old_values,{"first_name":first,"last_name":last,"class_id":request.form.get("class_id") or None})
            db.commit()
            flash("Dossier élève mis à jour.", "success")
            return redirect(url_for("students"))
    return render_template("student_form.html", classes=classes, parents=parents, student_users=student_users, student=student)


@app.route("/students/import.csv", methods=["POST"])
@login_required("admin", "secretary")
def students_import():
    import csv, io
    upload=request.files.get("file")
    if not upload or not (upload.filename or "").lower().endswith(".csv"): 
        flash("Sélectionne un fichier CSV valide.","danger")
        return redirect(url_for("students"))
    try:
        text=upload.stream.read().decode("utf-8-sig")
        reader=csv.DictReader(io.StringIO(text))
        db=get_db(); added=0
        for row in reader:
            first=(row.get("prenom") or "").strip(); last=(row.get("nom") or "").strip()
            birth_date=(row.get("date_naissance", "") or "").strip()
            if first and last and is_valid_birth_date(birth_date):
                db.execute("INSERT INTO students(first_name,last_name,birth_date,parent_name,parent_phone,school_year) VALUES(?,?,?,?,?,?)",(first,last,birth_date,row.get("parent", ""),row.get("telephone", ""),row.get("annee_scolaire", "2026-2027")))
                added+=1
        db.commit(); flash(f"{added} dossier(s) importé(s). Les classes doivent être affectées dans l'application.","success")
    except (UnicodeDecodeError, csv.Error):
        flash("Le CSV n'a pas pu être lu. Utilise l'export fourni comme modèle.","danger")
    return redirect(url_for("students"))


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required("admin")
def student_delete(student_id):
    db = get_db()
    db.execute("UPDATE students SET active=0 WHERE id=?", (student_id,))
    db.commit()
    flash("Élève archivé (suppression logique).", "success")
    return redirect(url_for("students"))

@app.route("/students/<int:student_id>/photo")
@login_required("admin", "teacher", "parent", "student", "secretary", "accountant")
def student_photo(student_id):
    db = get_db()
    student = db.execute("SELECT photo_path, parent_user_id, student_user_id, class_id FROM students WHERE id=? AND active=1", (student_id,)).fetchone()
    if not student or not student["photo_path"]:
        abort(404)
    role = session.get("role")
    if role == "parent" and student["parent_user_id"] != session["user_id"]:
        abort(403)
    if role == "student" and student["student_user_id"] != session["user_id"]:
        abort(403)
    if role == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=?", (session["user_id"], student["class_id"])).fetchone():
        abort(403)
    path = Path(app.config["UPLOAD_FOLDER"]) / student["photo_path"]
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg")


@app.route("/students/<int:student_id>")
@login_required("admin", "teacher", "parent", "student", "secretary", "accountant")
def student_detail(student_id):
    db = get_db()
    student = db.execute(
        "SELECT s.*, c.name AS class_name, u.email AS parent_email "
        "FROM students s "
        "LEFT JOIN classes c ON c.id=s.class_id "
        "LEFT JOIN users u ON u.id=s.parent_user_id "
        "WHERE s.id=? AND s.active=1",
        (student_id,)
    ).fetchone()
    if not student:
        abort(404)
    role = session.get("role")
    if role == "parent" and student["parent_user_id"] != session["user_id"]:
        abort(403)
    if role == "student" and student["student_user_id"] != session["user_id"]:
        abort(403)
    if role == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=?", (session["user_id"], student["class_id"])).fetchone():
        abort(403)

    # Grades
    grades = db.execute(
        "SELECT g.*, e.title AS evaluation_title, e.max_score, sub.name AS subject_name "
        "FROM grades g "
        "JOIN evaluations e ON e.id=g.evaluation_id "
        "JOIN subjects sub ON sub.id=e.subject_id "
        "WHERE g.student_id=? ORDER BY e.evaluation_date DESC",
        (student_id,)
    ).fetchall()

    # Absences
    absences = db.execute(
        "SELECT * FROM absences WHERE student_id=? ORDER BY absence_date DESC",
        (student_id,)
    ).fetchall()

    # Financial overview
    due = db.execute("SELECT COALESCE(SUM(amount), 0) FROM fee_schedules WHERE school_year=?", (student["school_year"],)).fetchone()[0]
    paid = db.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE student_id=? AND school_year=?", (student_id, student["school_year"])).fetchone()[0]
    finance = {"due": due, "paid": paid, "remaining": max(0, due - paid)}

    payments = db.execute("SELECT * FROM payments WHERE student_id=? ORDER BY paid_at DESC", (student_id,)).fetchall()

    return render_template(
        "student_detail.html",
        student=student,
        grades=grades,
        absences=absences,
        finance=finance,
        payments=payments
    )


@app.route("/classes", methods=["GET", "POST"])
@login_required("admin", "teacher", "secretary")
def classes():
    db = get_db()
    role = session.get("role")
    if request.method == "POST":
        if role not in ("admin", "director", "superadmin"):
            abort(403)
        name, level = request.form.get("name", "").strip(), request.form.get("level", "").strip()
        try:
            capacity = int(request.form.get("capacity", "30"))
            if not name or not level or capacity < 1:
                raise ValueError
            db.execute("INSERT INTO classes(name,level,section,capacity,school_year) VALUES(?,?,?,?,?)",
                       (name,level,request.form.get("section", "").strip(),capacity,request.form.get("school_year", "2026-2027").strip()))
            db.commit()
            flash("Classe créée.", "success")
            return redirect(url_for("classes"))
        except ValueError:
            flash("Vérifie le nom, le niveau et la capacité de la classe.", "danger")
    rows = db.execute("SELECT c.*, COUNT(s.id) AS student_count FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.active=1 WHERE (? IN ('admin', 'director', 'superadmin', 'secretary') OR c.id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)) GROUP BY c.id ORDER BY c.level,c.name",(role, session["user_id"])).fetchall()
    return render_template("classes.html", classes=rows)


@app.route("/classes/<int:class_id>/delete", methods=["POST"])
@login_required("admin")
def class_delete(class_id):
    db = get_db()
    count = db.execute("SELECT (SELECT COUNT(*) FROM students WHERE class_id=?)+(SELECT COUNT(*) FROM timetable WHERE class_id=?)+(SELECT COUNT(*) FROM evaluations WHERE class_id=?)+(SELECT COUNT(*) FROM teacher_assignments WHERE class_id=?)+(SELECT COUNT(*) FROM homework WHERE class_id=?)", (class_id,class_id,class_id,class_id,class_id)).fetchone()[0]
    if count:
        flash("Impossible de supprimer une classe référencée. Réaffectez les élèves et retirez d'abord ses créneaux, notes et affectations.", "danger")
    else:
        db.execute("DELETE FROM classes WHERE id=?", (class_id,))
        db.commit()
        flash("Classe supprimée.", "success")
    return redirect(url_for("classes"))

@app.route("/classes/<int:class_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def class_edit(class_id):
    db = get_db()
    cls = db.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
    if not cls:
        abort(404)
    if request.method == "POST":
        name, level = request.form.get("name", "").strip(), request.form.get("level", "").strip()
        try:
            capacity = int(request.form.get("capacity", "30"))
            year = request.form.get("school_year", "2026-2027").strip()
            section = request.form.get("section", "").strip()
            if not name or not level or capacity < 1:
                raise ValueError
            current_count = db.execute("SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1", (class_id, year)).fetchone()[0]
            if current_count > capacity:
                flash(f"La capacité ne peut pas être inférieure à l'effectif actuel ({current_count} élèves).", "danger")
                return render_template("class_form.html", cls=cls)
            old_vals = {"name": cls["name"], "level": cls["level"], "capacity": cls["capacity"], "section": cls["section"], "school_year": cls["school_year"]}
            db.execute("UPDATE classes SET name=?, level=?, section=?, capacity=?, school_year=? WHERE id=?",
                       (name, level, section, capacity, year, class_id))
            audit("update", "class", class_id, old_vals, {"name": name, "level": level, "capacity": capacity})
            db.commit()
            flash("Classe mise à jour avec succès.", "success")
            return redirect(url_for("classes"))
        except ValueError:
            flash("Vérifie le nom, le niveau et la capacité de la classe.", "danger")
    return render_template("class_form.html", cls=cls)


@app.route("/subjects", methods=["GET", "POST"])
@login_required("admin", "teacher")
def subjects():
    db = get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin", "director", "superadmin"): abort(403)
        name, level = request.form.get("name", "").strip(), request.form.get("level", "").strip()
        try:
            coefficient = float(request.form.get("coefficient", "1"))
            if not name or not level or not math.isfinite(coefficient) or coefficient <= 0: raise ValueError
            db.execute("INSERT INTO subjects(name,coefficient,level,school_year) VALUES(?,?,?,?)",
                       (name, coefficient, level, request.form.get("school_year", "2026-2027").strip()))
            db.commit()
            flash("Matière ajoutée.", "success")
            return redirect(url_for("subjects"))
        except ValueError:
            flash("Nom, niveau et coefficient positif obligatoires.", "danger")
    if session.get("role")=="teacher":
        rows=db.execute("SELECT * FROM subjects WHERE active=1 AND id IN (SELECT subject_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY level,name",(session["user_id"],)).fetchall()
    else:
        rows=db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY level,name").fetchall()
    return render_template("subjects.html", subjects=rows)


@app.route("/subjects/<int:item_id>/delete", methods=["POST"])
@login_required("admin")
def subject_delete(item_id):
    db = get_db()
    related = db.execute("SELECT (SELECT COUNT(*) FROM evaluations WHERE subject_id=?)+(SELECT COUNT(*) FROM teacher_assignments WHERE subject_id=?)+(SELECT COUNT(*) FROM homework WHERE subject_id=?)+(SELECT COUNT(*) FROM timetable WHERE subject_id=?)", (item_id,item_id,item_id,item_id)).fetchone()[0]
    if related:
        db.execute("UPDATE subjects SET active=0 WHERE id=?", (item_id,))
        flash("Matière archivée pour préserver l'historique.", "warning")
    else:
        db.execute("DELETE FROM subjects WHERE id=?", (item_id,))
        flash("Matière supprimée.", "success")
    db.commit()
    return redirect(url_for("subjects"))

@app.route("/subjects/<int:item_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def subject_edit(item_id):
    db = get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id=? AND active=1", (item_id,)).fetchone()
    if not subject:
        abort(404)
    if request.method == "POST":
        name, level = request.form.get("name", "").strip(), request.form.get("level", "").strip()
        try:
            coefficient = float(request.form.get("coefficient", "1"))
            year = request.form.get("school_year", "2026-2027").strip()
            if not name or not level or not math.isfinite(coefficient) or coefficient <= 0:
                raise ValueError
            old_vals = {"name": subject["name"], "level": subject["level"], "coefficient": subject["coefficient"], "school_year": subject["school_year"]}
            db.execute("UPDATE subjects SET name=?, level=?, coefficient=?, school_year=? WHERE id=?",
                       (name, level, coefficient, year, item_id))
            audit("update", "subject", item_id, old_vals, {"name": name, "level": level, "coefficient": coefficient})
            db.commit()
            flash("Matière mise à jour.", "success")
            return redirect(url_for("subjects"))
        except ValueError:
            flash("Nom, niveau et coefficient positif obligatoires.", "danger")
    return render_template("subject_form.html", subject=subject)


@app.route("/timetable", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student", "director")
def timetable():
    db = get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin", "director", "superadmin"): abort(403)
        try:
            class_id, teacher_id, subject_id = (int(request.form[k]) for k in ("class_id", "teacher_id", "subject_id"))
            room_id = int(request.form["room_id"]) if request.form.get("room_id") else None
            day = int(request.form["weekday"])
            year=request.form.get("school_year","2026-2027").strip()
            start, end = request.form["start_time"], request.form["end_time"]
            datetime.strptime(start,"%H:%M"); datetime.strptime(end,"%H:%M")
            if day not in range(1,8) or not start < end: raise ValueError
            school_class=db.execute("SELECT capacity,school_year,level,(SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1) AS count FROM classes WHERE id=?",(class_id,year,class_id)).fetchone()
            valid_teacher=db.execute("SELECT 1 FROM users WHERE id=? AND role='teacher' AND active=1",(teacher_id,)).fetchone()
            valid_subject=db.execute("SELECT level FROM subjects WHERE id=? AND active=1 AND school_year=?",(subject_id,year)).fetchone()
            valid_assignment=db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?",(teacher_id,class_id,subject_id,year)).fetchone()
            if not school_class or school_class["school_year"]!=year or not valid_teacher or not valid_subject or valid_subject["level"]!=school_class["level"] or not valid_assignment: raise ValueError
            if room_id:
                room=db.execute("SELECT capacity,school_year FROM rooms WHERE id=? AND active=1",(room_id,)).fetchone()
                if not room or room["school_year"]!=year or room["capacity"]<school_class["count"]: raise ValueError
            conflict = db.execute("SELECT id FROM timetable WHERE school_year=? AND weekday=? AND start_time < ? AND end_time > ? AND (teacher_id=? OR class_id=? OR (? IS NOT NULL AND room_id=?))", (year,day,end,start,teacher_id,class_id,room_id,room_id)).fetchone()
            if conflict:
                flash("Conflit : enseignant, classe ou salle déjà occupé(e) sur ce créneau.", "danger")
            else:
                db.execute("INSERT INTO timetable(class_id,teacher_id,subject_id,room_id,weekday,start_time,end_time,school_year) VALUES(?,?,?,?,?,?,?,?)", (class_id,teacher_id,subject_id,room_id,day,start,end,year))
                db.commit()
                flash("Créneau ajouté à l'emploi du temps.", "success")
                return redirect(url_for("timetable"))
        except (ValueError, KeyError):
            flash("Informations de créneau invalides.", "danger")
    schedule_sql="SELECT t.*,c.name class_name,s.name subject_name,u.username teacher_name,r.name room_name FROM timetable t JOIN classes c ON c.id=t.class_id JOIN subjects s ON s.id=t.subject_id JOIN users u ON u.id=t.teacher_id LEFT JOIN rooms r ON r.id=t.room_id"
    role=session.get("role")
    if role=="teacher":
        rows=db.execute(schedule_sql+" WHERE t.teacher_id=? ORDER BY weekday,start_time",(session["user_id"],)).fetchall()
    elif role=="parent":
        rows=db.execute(schedule_sql+" WHERE t.class_id IN (SELECT class_id FROM students WHERE parent_user_id=?) ORDER BY weekday,start_time",(session["user_id"],)).fetchall()
    elif role=="student":
        rows=db.execute(schedule_sql+" WHERE t.class_id IN (SELECT class_id FROM students WHERE student_user_id=?) ORDER BY weekday,start_time",(session["user_id"],)).fetchall()
    else:
        rows=db.execute(schedule_sql+" ORDER BY weekday,start_time").fetchall()
    return render_template("timetable.html", slots=rows,
        classes=db.execute("SELECT * FROM classes ORDER BY name").fetchall(),
        teachers=db.execute("SELECT * FROM users WHERE role='teacher' AND active=1 ORDER BY username").fetchall(),
        subjects=db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall(),
        rooms=db.execute("SELECT * FROM rooms WHERE active=1 ORDER BY name").fetchall())

@app.route("/timetable/<int:slot_id>/delete", methods=["POST"])
@login_required("admin")
def timetable_delete(slot_id):
    db = get_db()
    slot = db.execute("SELECT * FROM timetable WHERE id=?", (slot_id,)).fetchone()
    if not slot:
        abort(404)
    db.execute("DELETE FROM timetable WHERE id=?", (slot_id,))
    audit("delete", "timetable", slot_id, {"class_id": slot["class_id"], "weekday": slot["weekday"], "start_time": slot["start_time"]})
    db.commit()
    flash("Créneau supprimé de l'emploi du temps.", "success")
    return redirect(url_for("timetable"))


@app.route("/timetable/<int:slot_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def timetable_edit(slot_id):
    db = get_db()
    slot = db.execute("SELECT * FROM timetable WHERE id=?", (slot_id,)).fetchone()
    if not slot:
        abort(404)
    classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()
    teachers = db.execute("SELECT * FROM users WHERE role='teacher' AND active=1 ORDER BY username").fetchall()
    subjects = db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall()
    rooms = db.execute("SELECT * FROM rooms WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        try:
            class_id, teacher_id, subject_id = (int(request.form[k]) for k in ("class_id", "teacher_id", "subject_id"))
            room_id = int(request.form["room_id"]) if request.form.get("room_id") else None
            day = int(request.form["weekday"])
            year = request.form.get("school_year", "2026-2027").strip()
            start, end = request.form["start_time"], request.form["end_time"]
            datetime.strptime(start, "%H:%M")
            datetime.strptime(end, "%H:%M")
            if day not in range(1, 8) or not start < end:
                raise ValueError
            school_class = db.execute("SELECT capacity,school_year,level,(SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1) AS count FROM classes WHERE id=?", (class_id, year, class_id)).fetchone()
            valid_teacher = db.execute("SELECT 1 FROM users WHERE id=? AND role='teacher' AND active=1", (teacher_id,)).fetchone()
            valid_subject = db.execute("SELECT level FROM subjects WHERE id=? AND active=1 AND school_year=?", (subject_id, year)).fetchone()
            valid_assignment = db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (teacher_id, class_id, subject_id, year)).fetchone()
            if not school_class or school_class["school_year"] != year or not valid_teacher or not valid_subject or valid_subject["level"] != school_class["level"] or not valid_assignment:
                raise ValueError
            if room_id:
                room = db.execute("SELECT capacity,school_year FROM rooms WHERE id=? AND active=1", (room_id,)).fetchone()
                if not room or room["school_year"] != year or room["capacity"] < school_class["count"]:
                    raise ValueError
            conflict = db.execute("SELECT id FROM timetable WHERE id<>? AND school_year=? AND weekday=? AND start_time < ? AND end_time > ? AND (teacher_id=? OR class_id=? OR (? IS NOT NULL AND room_id=?))", (slot_id, year, day, end, start, teacher_id, class_id, room_id, room_id)).fetchone()
            if conflict:
                flash("Conflit : enseignant, classe ou salle déjà occupé(e) sur ce créneau.", "danger")
                return render_template("timetable_form.html", slot=slot, classes=classes, teachers=teachers, subjects=subjects, rooms=rooms)
            old_vals = {"class_id": slot["class_id"], "teacher_id": slot["teacher_id"], "weekday": slot["weekday"], "start_time": slot["start_time"], "end_time": slot["end_time"]}
            db.execute("UPDATE timetable SET class_id=?, teacher_id=?, subject_id=?, room_id=?, weekday=?, start_time=?, end_time=?, school_year=? WHERE id=?",
                       (class_id, teacher_id, subject_id, room_id, day, start, end, year, slot_id))
            audit("update", "timetable", slot_id, old_vals, {"class_id": class_id, "weekday": day, "start_time": start, "end_time": end})
            db.commit()
            flash("Créneau mis à jour avec succès.", "success")
            return redirect(url_for("timetable"))
        except (ValueError, KeyError):
            flash("Informations de créneau invalides.", "danger")
    return render_template("timetable_form.html", slot=slot, classes=classes, teachers=teachers, subjects=subjects, rooms=rooms)


@app.route("/grades", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student")
def grades():
    db = get_db()
    if request.method == "POST":
        if session.get("role") in ("parent", "student"): abort(403)
        try:
            evaluation_id, student_id = int(request.form["evaluation_id"]), int(request.form["student_id"])
            score = float(request.form["score"])
            evaluation = db.execute("SELECT max_score,class_id,subject_id,school_year FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
            student = db.execute("SELECT class_id FROM students WHERE id=? AND active=1", (student_id,)).fetchone()
            if not evaluation or not student or not math.isfinite(score) or student["class_id"] != evaluation["class_id"] or score < 0 or score > evaluation["max_score"]: raise ValueError
            if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?",(session["user_id"],evaluation["class_id"],evaluation["subject_id"],evaluation["school_year"])).fetchone(): abort(403)
            db.execute("INSERT INTO grades(evaluation_id,student_id,score,comment) VALUES(?,?,?,?) ON CONFLICT(evaluation_id,student_id) DO UPDATE SET score=excluded.score,comment=excluded.comment", (evaluation_id,student_id,score,request.form.get("comment", "").strip()))
            db.commit()
            flash("Note enregistrée.", "success")
        except (ValueError, KeyError):
            flash("Vérifie l'évaluation, l'élève et la note (maximum autorisé).", "danger")
        return redirect(url_for("grades"))
    elif session.get("role")=="teacher":
        evals=db.execute("SELECT e.*,s.name subject_name,c.name class_name FROM evaluations e JOIN subjects s ON s.id=e.subject_id JOIN classes c ON c.id=e.class_id JOIN teacher_assignments a ON a.class_id=e.class_id AND a.subject_id=e.subject_id WHERE a.teacher_id=? ORDER BY e.evaluation_date DESC",(session["user_id"],)).fetchall()
    elif session.get("role")=="student":
        evals=db.execute("SELECT e.*,s.name subject_name,c.name class_name FROM evaluations e JOIN subjects s ON s.id=e.subject_id JOIN classes c ON c.id=e.class_id WHERE e.class_id IN (SELECT class_id FROM students WHERE student_user_id=?) ORDER BY e.evaluation_date DESC",(session["user_id"],)).fetchall()
    else:
        evals = db.execute("SELECT e.*,s.name subject_name,c.name class_name FROM evaluations e JOIN subjects s ON s.id=e.subject_id JOIN classes c ON c.id=e.class_id ORDER BY e.evaluation_date DESC").fetchall()
    if session.get("role") == "parent":
        rows = db.execute("SELECT g.*,e.title evaluation_title,s.first_name,s.last_name FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN students s ON s.id=g.student_id WHERE s.parent_user_id=? ORDER BY e.evaluation_date DESC,s.last_name", (session["user_id"],)).fetchall()
        evals = [e for e in evals if db.execute("SELECT 1 FROM students WHERE class_id=? AND parent_user_id=?", (e["class_id"], session["user_id"])).fetchone()]
    elif session.get("role")=="student":
        rows=db.execute("SELECT g.*,e.title evaluation_title,s.first_name,s.last_name FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN students s ON s.id=g.student_id WHERE s.student_user_id=? ORDER BY e.evaluation_date DESC",(session["user_id"],)).fetchall()
        evals=[e for e in evals if db.execute("SELECT 1 FROM students WHERE class_id=? AND student_user_id=?",(e["class_id"],session["user_id"])).fetchone()]
    elif session.get("role")=="teacher":
        rows=db.execute("SELECT g.*,e.title evaluation_title,s.first_name,s.last_name FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN students s ON s.id=g.student_id JOIN teacher_assignments a ON a.class_id=e.class_id AND a.subject_id=e.subject_id WHERE a.teacher_id=? ORDER BY e.evaluation_date DESC,s.last_name",(session["user_id"],)).fetchall()
    else:
        rows = db.execute("SELECT g.*,e.title evaluation_title,s.first_name,s.last_name FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN students s ON s.id=g.student_id ORDER BY e.evaluation_date DESC,s.last_name").fetchall()
    return render_template("grades.html", evaluations=evals, grades=rows,
        students=db.execute("SELECT * FROM students WHERE active=1 AND (? <> 'parent' OR parent_user_id=?) AND (? <> 'teacher' OR class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)) AND (? <> 'student' OR student_user_id=?) ORDER BY last_name",(session.get("role"),session["user_id"],session.get("role"),session["user_id"],session.get("role"),session["user_id"])).fetchall(),
        subjects=db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall(),
        classes=db.execute("SELECT * FROM classes ORDER BY name").fetchall())


@app.route("/exams", methods=["GET", "POST"])
@app.route("/controles", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student", "secretary", "director")
def exams():
    db = get_db()
    today_str = date.today().isoformat()
    role = session.get("role")
    user_id = session.get("user_id")

    if request.method == "POST":
        if role not in ("admin", "teacher", "director"):
            abort(403)
        try:
            title = request.form["title"].strip()
            eval_type = request.form.get("eval_type", "Devoir Surveillé").strip()
            subject_id = int(request.form["subject_id"])
            class_id = int(request.form["class_id"])
            maximum = float(request.form.get("max_score", 20))
            room_id = int(request.form["room_id"]) if request.form.get("room_id") else None
            evaluation_date = parse_iso_date(request.form["evaluation_date"]).isoformat()
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()
            instructions = request.form.get("instructions", "").strip()

            school_class = db.execute("SELECT level, school_year FROM classes WHERE id=?", (class_id,)).fetchone()
            subject = db.execute("SELECT level, school_year FROM subjects WHERE id=? AND active=1", (subject_id,)).fetchone()
            if not title or not math.isfinite(maximum) or maximum <= 0 or not school_class or not subject or school_class["level"] != subject["level"] or school_class["school_year"] != subject["school_year"]:
                raise ValueError("Informations de l'épreuve ou cohérence de niveau invalides.")
            if role == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (user_id, class_id, subject_id, school_class["school_year"])).fetchone():
                abort(403)

            if start_time and end_time:
                try:
                    t_start = datetime.strptime(start_time, "%H:%M")
                    t_end = datetime.strptime(end_time, "%H:%M")
                    if t_start >= t_end:
                        raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")
                except ValueError as ve:
                    if "L'heure de fin" in str(ve):
                        raise
                    raise ValueError("Format d'heure invalide (HH:MM attendu).")

            if room_id:
                room = db.execute("SELECT capacity, school_year FROM rooms WHERE id=? AND active=1", (room_id,)).fetchone()
                class_students = db.execute("SELECT COUNT(*) FROM students WHERE class_id=? AND school_year=? AND active=1", (class_id, school_class["school_year"])).fetchone()[0]
                if room and room["capacity"] < class_students:
                    raise ValueError(f"La capacité de la salle ({room['capacity']} places) est inférieure au nombre d'élèves de la classe ({class_students} élèves).")

            if room_id and start_time and end_time:
                room_conflict = db.execute("""
                    SELECT title FROM evaluations
                    WHERE evaluation_date=? AND room_id=?
                      AND start_time != '' AND end_time != ''
                      AND start_time < ? AND end_time > ?
                """, (evaluation_date, room_id, end_time, start_time)).fetchone()
                if room_conflict:
                    raise ValueError(f"La salle est déjà réservée pour « {room_conflict['title']} » sur ce créneau.")

            if start_time and end_time:
                class_conflict = db.execute("""
                    SELECT title FROM evaluations
                    WHERE evaluation_date=? AND class_id=?
                      AND start_time != '' AND end_time != ''
                      AND start_time < ? AND end_time > ?
                """, (evaluation_date, class_id, end_time, start_time)).fetchone()
                if class_conflict:
                    raise ValueError(f"Cette classe a déjà l'épreuve « {class_conflict['title']} » programmée sur ce créneau.")

            db.execute("""
                INSERT INTO evaluations(title, subject_id, class_id, evaluation_date, max_score, school_year, eval_type, start_time, end_time, room_id, instructions)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (title, subject_id, class_id, evaluation_date, maximum, school_class["school_year"], eval_type, start_time, end_time, room_id, instructions))
            db.commit()
            flash("Contrôle / Évaluation planifié(e) avec succès.", "success")
        except (ValueError, KeyError) as e:
            flash(str(e) if str(e) else "Vérifie les informations de l'évaluation.", "danger")
        return redirect(url_for("exams"))

    # Query evaluations based on user role
    query = """
        SELECT e.*, s.name AS subject_name, s.coefficient AS subject_coeff, c.name AS class_name,
               r.name AS room_name,
               (SELECT COUNT(*) FROM grades g WHERE g.evaluation_id = e.id) AS grades_count
        FROM evaluations e
        JOIN subjects s ON s.id = e.subject_id
        JOIN classes c ON c.id = e.class_id
        LEFT JOIN rooms r ON r.id = e.room_id
    """
    params = []
    if role == "student":
        query += " WHERE e.class_id IN (SELECT class_id FROM students WHERE student_user_id=?)"
        params.append(user_id)
    elif role == "parent":
        query += " WHERE e.class_id IN (SELECT class_id FROM students WHERE parent_user_id=?)"
        params.append(user_id)
    elif role == "teacher":
        query += " WHERE EXISTS (SELECT 1 FROM teacher_assignments a WHERE a.teacher_id=? AND a.class_id=e.class_id AND a.subject_id=e.subject_id)"
        params.append(user_id)

    query += " ORDER BY e.evaluation_date ASC, e.start_time ASC"
    raw_exams = db.execute(query, params).fetchall()
    exam_rows = [dict(row) for row in raw_exams]

    if role == "teacher":
        subjects = db.execute("SELECT * FROM subjects WHERE active=1 AND id IN (SELECT subject_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY name", (user_id,)).fetchall()
        classes = db.execute("SELECT * FROM classes WHERE id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY name", (user_id,)).fetchall()
    else:
        subjects = db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall()
        classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()

    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()

    return render_template("exams.html", exams=exam_rows, subjects=subjects, classes=classes, rooms=rooms, today=today_str)


@app.route("/calendar", methods=["GET", "POST"])
@app.route("/agenda", methods=["GET", "POST"])
@login_required()
def calendar_view():
    db = get_db()
    today = date.today()
    today_str = today.isoformat()
    role = session.get("role")
    user_id = session.get("user_id")

    if request.method == "POST":
        if role not in ("admin", "teacher", "director"):
            abort(403)
        try:
            title = request.form["title"].strip()
            event_type = request.form.get("event_type", "event").strip()
            audience = request.form.get("audience", "all").strip()
            start_date = parse_iso_date(request.form["start_date"]).isoformat()
            end_date_raw = request.form.get("end_date", "").strip()
            end_date = parse_iso_date(end_date_raw).isoformat() if end_date_raw else ""
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()
            description = request.form.get("description", "").strip()

            if not title:
                raise ValueError("L'intitulé de l'événement est obligatoire.")
            if end_date and end_date < start_date:
                raise ValueError("La date de fin ne peut pas être antérieure à la date de début.")

            if start_time and end_time:
                try:
                    t_start = datetime.strptime(start_time, "%H:%M")
                    t_end = datetime.strptime(end_time, "%H:%M")
                    if (not end_date or end_date == start_date) and t_start >= t_end:
                        raise ValueError("L'heure de fin de l'événement doit être postérieure à l'heure de début.")
                except ValueError as ve:
                    if "L'heure de fin" in str(ve):
                        raise
                    raise ValueError("Format d'heure invalide (HH:MM attendu).")

            db.execute("""
                INSERT INTO school_events(title, event_type, start_date, end_date, start_time, end_time, description, audience, school_year, created_by, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (title, event_type, start_date, end_date, start_time, end_time, description, audience, "2026-2027", user_id, datetime.now().isoformat(timespec="seconds")))
            db.commit()
            flash("Événement ajouté au calendrier scolaire.", "success")
        except (ValueError, KeyError) as exc:
            flash(str(exc) or "Vérifie les informations de l'événement.", "danger")
        return redirect(url_for("calendar_view"))

    try:
        req_month = int(request.args.get("month", today.month))
        req_year = int(request.args.get("year", today.year))
        if not (1 <= req_month <= 12 and 2000 <= req_year <= 2100):
            req_month, req_year = today.month, today.year
    except (ValueError, TypeError):
        req_month, req_year = today.month, today.year

    if req_month == 1:
        prev_month, prev_year = 12, req_year - 1
    else:
        prev_month, prev_year = req_month - 1, req_year

    if req_month == 12:
        next_month, next_year = 1, req_year + 1
    else:
        next_month, next_year = req_month + 1, req_year

    month_names_fr = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    month_name = month_names_fr[req_month - 1]

    # 1. Homeworks
    hw_query = """
        SELECT h.id, h.title, h.due_date, h.description, s.name AS subject_name, c.name AS class_name, u.username AS teacher_name
        FROM homework h
        JOIN subjects s ON s.id = h.subject_id
        JOIN classes c ON c.id = h.class_id
        JOIN users u ON u.id = h.teacher_id
        WHERE h.active = 1
    """
    hw_params = []
    if role == "student":
        hw_query += " AND h.class_id IN (SELECT class_id FROM students WHERE student_user_id=?)"
        hw_params.append(user_id)
    elif role == "parent":
        hw_query += " AND h.class_id IN (SELECT class_id FROM students WHERE parent_user_id=?)"
        hw_params.append(user_id)
    elif role == "teacher":
        hw_query += " AND EXISTS (SELECT 1 FROM teacher_assignments a WHERE a.teacher_id=? AND a.class_id=h.class_id AND a.subject_id=h.subject_id)"
        hw_params.append(user_id)

    homeworks = db.execute(hw_query, hw_params).fetchall()

    # 2. Evaluations / Exams
    ev_query = """
        SELECT e.id, e.title, e.evaluation_date, e.eval_type, e.start_time, e.end_time, e.instructions,
               s.name AS subject_name, c.name AS class_name, r.name AS room_name
        FROM evaluations e
        JOIN subjects s ON s.id = e.subject_id
        JOIN classes c ON c.id = e.class_id
        LEFT JOIN rooms r ON r.id = e.room_id
    """
    ev_params = []
    if role == "student":
        ev_query += " WHERE e.class_id IN (SELECT class_id FROM students WHERE student_user_id=?)"
        ev_params.append(user_id)
    elif role == "parent":
        ev_query += " WHERE e.class_id IN (SELECT class_id FROM students WHERE parent_user_id=?)"
        ev_params.append(user_id)
    elif role == "teacher":
        ev_query += " WHERE EXISTS (SELECT 1 FROM teacher_assignments a WHERE a.teacher_id=? AND a.class_id=e.class_id AND a.subject_id=e.subject_id)"
        ev_params.append(user_id)

    evals = db.execute(ev_query, ev_params).fetchall()

    # 3. School events
    se_query = "SELECT * FROM school_events WHERE school_year='2026-2027'"
    if role == "student":
        se_query += " AND audience IN ('all', 'students')"
    elif role == "parent":
        se_query += " AND audience IN ('all', 'parents')"
    elif role == "teacher":
        se_query += " AND audience IN ('all', 'teachers')"
    school_ev_list = db.execute(se_query).fetchall()

    date_events = {}
    upcoming_list = []

    for hw in homeworks:
        d = hw["due_date"]
        item = {
            "id": f"hw-{hw['id']}",
            "title": hw["title"],
            "type": "homework",
            "type_label": "Devoir à rendre",
            "badge_class": "badge-homework",
            "color": "#7c3aed",
            "icon": "fa-book-bookmark",
            "subject": hw["subject_name"],
            "class": hw["class_name"],
            "date": d,
            "time": "Date limite",
            "room": "",
            "teacher": hw["teacher_name"],
            "details": hw["description"] or "Consulter l'espace devoirs pour les détails et le dépôt.",
        }
        date_events.setdefault(d, []).append(item)
        if d >= today_str:
            upcoming_list.append(item)

    for ex in evals:
        d = ex["evaluation_date"]
        time_display = f"{ex['start_time']} - {ex['end_time']}" if ex["start_time"] and ex["end_time"] else (ex["start_time"] or "Heure de cours")
        etype = ex["eval_type"] or "Contrôle"
        item = {
            "id": f"ex-{ex['id']}",
            "title": ex["title"],
            "type": "exam",
            "type_label": etype,
            "badge_class": "badge-exam",
            "color": "#dc2626",
            "icon": "fa-stopwatch",
            "subject": ex["subject_name"],
            "class": ex["class_name"],
            "date": d,
            "time": time_display,
            "room": ex["room_name"] or "",
            "teacher": "",
            "details": ex["instructions"] or "Révisions recommandées.",
        }
        date_events.setdefault(d, []).append(item)
        if d >= today_str:
            upcoming_list.append(item)

    for se in school_ev_list:
        start_d = se["start_date"]
        end_d = se["end_date"] or start_d
        time_display = f"{se['start_time']} - {se['end_time']}" if se["start_time"] and se["end_time"] else (se["start_time"] or "Journée entière")
        item = {
            "id": f"se-{se['id']}",
            "title": se["title"],
            "type": "event",
            "type_label": "Événement scolaire",
            "badge_class": "badge-event",
            "color": "#2563eb",
            "icon": "fa-calendar-check",
            "subject": "",
            "class": "",
            "date": start_d,
            "time": time_display,
            "room": "",
            "teacher": "",
            "details": se["description"] or "",
        }
        try:
            curr = parse_iso_date(start_d)
            finish = parse_iso_date(end_d)
            step_limit = 35
            while curr <= finish and step_limit > 0:
                date_events.setdefault(curr.isoformat(), []).append(item)
                curr += timedelta(days=1)
                step_limit -= 1
        except Exception:
            date_events.setdefault(start_d, []).append(item)

        if end_d >= today_str:
            upcoming_list.append(item)

    upcoming_list.sort(key=lambda x: (x["date"], x.get("time", "")))

    cal = py_calendar.Calendar(firstweekday=0)
    month_dates = cal.monthdatescalendar(req_year, req_month)
    cells = []
    for week in month_dates:
        for day_obj in week:
            day_str = day_obj.isoformat()
            cells.append({
                "day": day_obj.day,
                "date": day_str,
                "is_current_month": (day_obj.month == req_month),
                "is_today": (day_obj == today),
                "events": date_events.get(day_str, [])
            })

    classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()
    subjects = db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall()

    return render_template(
        "calendar.html",
        cells=cells,
        upcoming=upcoming_list[:30],
        current_year=req_year,
        current_month=req_month,
        month_name=month_name,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        classes=classes,
        subjects=subjects,
        today=today_str,
    )


@app.route("/evaluations", methods=["GET", "POST"])
@login_required("admin", "teacher")
def evaluations():
    db = get_db()
    if request.method == "POST":
        try:
            title=request.form["title"].strip(); subject_id=int(request.form["subject_id"]); class_id=int(request.form["class_id"])
            maximum=float(request.form.get("max_score",20))
            school_class=db.execute("SELECT level,school_year FROM classes WHERE id=?",(class_id,)).fetchone()
            subject=db.execute("SELECT level,school_year FROM subjects WHERE id=? AND active=1",(subject_id,)).fetchone()
            if not title or not math.isfinite(maximum) or maximum <= 0 or not school_class or not subject or school_class["level"]!=subject["level"] or school_class["school_year"]!=subject["school_year"]: raise ValueError
            if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?",(session["user_id"],class_id,subject_id,school_class["school_year"])).fetchone(): abort(403)
            evaluation_date = parse_iso_date(request.form["evaluation_date"])
            db.execute("INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year) VALUES(?,?,?,?,?,?)", (title,subject_id,class_id,evaluation_date.isoformat(),maximum,school_class["school_year"]))
            db.commit(); flash("Évaluation créée.", "success")
        except (ValueError, KeyError): flash("Vérifie les informations de l'évaluation.", "danger")
        return redirect(url_for("grades"))
    return redirect(url_for("grades"))

@app.route("/evaluations/<int:eval_id>/edit", methods=["GET", "POST"])
@login_required("admin", "teacher", "director")
def evaluation_edit(eval_id):
    db = get_db()
    ev = db.execute("SELECT * FROM evaluations WHERE id=?", (eval_id,)).fetchone()
    if not ev:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (session["user_id"], ev["class_id"], ev["subject_id"], ev["school_year"])).fetchone():
        abort(403)
    classes = db.execute("SELECT * FROM classes ORDER BY name").fetchall()
    subjects = db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        try:
            title = request.form["title"].strip()
            subject_id = int(request.form["subject_id"])
            class_id = int(request.form["class_id"])
            maximum = float(request.form.get("max_score", 20))
            school_class = db.execute("SELECT level,school_year FROM classes WHERE id=?", (class_id,)).fetchone()
            subject = db.execute("SELECT level,school_year FROM subjects WHERE id=? AND active=1", (subject_id,)).fetchone()
            if not title or not math.isfinite(maximum) or maximum <= 0 or not school_class or not subject or school_class["level"] != subject["level"] or school_class["school_year"] != subject["school_year"]:
                raise ValueError
            if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (session["user_id"], class_id, subject_id, school_class["school_year"])).fetchone():
                abort(403)
            highest_grade = db.execute("SELECT MAX(score) FROM grades WHERE evaluation_id=?", (eval_id,)).fetchone()[0]
            if highest_grade is not None and highest_grade > maximum:
                flash(f"La note maximale ne peut être inférieure à la note la plus élevée déjà saisie ({highest_grade}).", "danger")
                return render_template("evaluation_form.html", eval=ev, classes=classes, subjects=subjects)
            evaluation_date = parse_iso_date(request.form["evaluation_date"])
            old_vals = {"title": ev["title"], "max_score": ev["max_score"], "evaluation_date": ev["evaluation_date"]}
            db.execute("UPDATE evaluations SET title=?, subject_id=?, class_id=?, evaluation_date=?, max_score=?, school_year=? WHERE id=?",
                       (title, subject_id, class_id, evaluation_date.isoformat(), maximum, school_class["school_year"], eval_id))
            audit("update", "evaluation", eval_id, old_vals, {"title": title, "max_score": maximum})
            db.commit()
            flash("Évaluation mise à jour.", "success")
            redirect_target = url_for("exams") if (request.referrer and "exams" in request.referrer) else url_for("grades")
            return redirect(redirect_target)
        except (ValueError, KeyError):
            flash("Vérifie les informations de l'évaluation.", "danger")
    return render_template("evaluation_form.html", eval=ev, classes=classes, subjects=subjects)


@app.route("/evaluations/<int:eval_id>/delete", methods=["POST"])
@login_required("admin", "teacher", "director")
def evaluation_delete(eval_id):
    db = get_db()
    ev = db.execute("SELECT * FROM evaluations WHERE id=?", (eval_id,)).fetchone()
    if not ev:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (session["user_id"], ev["class_id"], ev["subject_id"], ev["school_year"])).fetchone():
        abort(403)
    db.execute("DELETE FROM grades WHERE evaluation_id=?", (eval_id,))
    db.execute("DELETE FROM evaluations WHERE id=?", (eval_id,))
    audit("delete", "evaluation", eval_id, {"title": ev["title"]})
    db.commit()
    flash("Évaluation et notes associées supprimées.", "success")
    redirect_target = url_for("exams") if (request.referrer and "exams" in request.referrer) else url_for("grades")
    return redirect(redirect_target)


@app.route("/grades/<int:grade_id>/delete", methods=["POST"])
@login_required("admin", "teacher")
def grade_delete(grade_id):
    db = get_db()
    gr = db.execute("SELECT g.*, e.class_id, e.subject_id, e.school_year FROM grades g JOIN evaluations e ON e.id=g.evaluation_id WHERE g.id=?", (grade_id,)).fetchone()
    if not gr:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (session["user_id"], gr["class_id"], gr["subject_id"], gr["school_year"])).fetchone():
        abort(403)
    db.execute("DELETE FROM grades WHERE id=?", (grade_id,))
    audit("delete", "grade", grade_id, {"score": gr["score"], "student_id": gr["student_id"]})
    db.commit()
    flash("Note supprimée.", "success")
    return redirect(url_for("grades"))


@app.route("/reports/bulletin/<int:student_id>.pdf")
@login_required("admin", "teacher", "parent", "student")
def bulletin_pdf(student_id):
    db=get_db()
    student=db.execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.active=1",(student_id,)).fetchone()
    if not student: abort(404)
    role=session.get("role")
    if role=="parent" and student["parent_user_id"] != session["user_id"]: abort(403)
    if role=="student" and student["student_user_id"] != session["user_id"]: abort(403)
    if role=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=?",(session["user_id"],student["class_id"])).fetchone(): abort(403)
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    if role=="teacher":
        results=db.execute("SELECT sub.name subject,sub.coefficient,ROUND(AVG(g.score/e.max_score*20),2) average,COUNT(g.id) count FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN subjects sub ON sub.id=e.subject_id WHERE g.student_id=? AND e.class_id=? AND e.subject_id IN (SELECT subject_id FROM teacher_assignments WHERE teacher_id=? AND class_id=?) GROUP BY sub.id ORDER BY sub.name",(student_id,student["class_id"],session["user_id"],student["class_id"])).fetchall()
    else:
        results=db.execute("SELECT sub.name subject,sub.coefficient,ROUND(AVG(g.score/e.max_score*20),2) average,COUNT(g.id) count FROM grades g JOIN evaluations e ON e.id=g.evaluation_id JOIN subjects sub ON sub.id=e.subject_id WHERE g.student_id=? GROUP BY sub.id ORDER BY sub.name",(student_id,)).fetchall()
    weighted=sum(row["average"]*row["coefficient"] for row in results)
    coefficients=sum(row["coefficient"] for row in results)
    average=weighted/coefficients if coefficients else None
    buffer=io.BytesIO(); page=canvas.Canvas(buffer,pagesize=A4)
    page.setTitle(f"Bulletin {student['last_name']} {student['first_name']}")
    page.setFont("Helvetica-Bold",20); page.drawString(55,785,"BULLETIN SCOLAIRE")
    page.setFont("Helvetica",12); page.drawString(55,750,f"Élève : {student['first_name']} {student['last_name']}")
    page.drawString(55,730,f"Classe : {student['class_name'] or 'Non affecté'} · Année : {student['school_year']}")
    page.setFont("Helvetica-Bold",11); page.drawString(55,690,"Matière"); page.drawString(310,690,"Moyenne / 20"); page.drawString(440,690,"Coef.")
    y=665; page.setFont("Helvetica",11)
    for row in results:
        page.drawString(55,y,row["subject"][:35]); page.drawString(325,y,f"{row['average']:.2f}"); page.drawString(450,y,f"{row['coefficient']:g}"); y-=24
        if y<100: page.showPage(); y=780; page.setFont("Helvetica",11)
    page.setFont("Helvetica-Bold",13); page.drawString(55,y-18,f"Moyenne générale pondérée : {average:.2f} / 20" if average is not None else "Moyenne générale : aucune note disponible")
    page.setFont("Helvetica-Oblique",9); page.drawString(55,55,"Document confidentiel destiné à la famille et à l'établissement.")
    page.save(); buffer.seek(0)
    return send_file(buffer,mimetype="application/pdf",as_attachment=True,download_name=f"bulletin-{student_id}.pdf")


@app.route("/payments/<int:payment_id>/receipt.pdf")
@login_required("admin", "accountant", "parent")
def payment_receipt(payment_id):
    db=get_db()
    payment=db.execute("SELECT p.*,s.first_name,s.last_name,s.parent_user_id FROM payments p JOIN students s ON s.id=p.student_id WHERE p.id=?",(payment_id,)).fetchone()
    if not payment: abort(404)
    if session.get("role")=="parent" and payment["parent_user_id"] != session["user_id"]: abort(403)
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    due=db.execute("SELECT COALESCE(SUM(amount),0) FROM fee_schedules WHERE school_year=?",(payment["school_year"],)).fetchone()[0]
    paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE student_id=? AND school_year=?",(payment["student_id"],payment["school_year"])).fetchone()[0]
    remaining=max(0,due-paid)
    buffer=io.BytesIO(); page=canvas.Canvas(buffer,pagesize=A4)
    page.setTitle(f"Reçu de paiement {payment_id}")
    page.setFont("Helvetica-Bold",20); page.drawString(60,780,"REÇU DE PAIEMENT")
    page.setFont("Helvetica",12)
    lines=[f"Numéro : REC-{payment_id:06d}",f"Date : {payment['paid_at']}",f"Élève : {payment['first_name']} {payment['last_name']}",f"Année scolaire : {payment['school_year']}",f"Montant reçu : {payment['amount']:.2f}",f"Mode de paiement : {payment['method']}",f"Référence : {payment['reference'] or '—'}",f"Solde calculé restant : {remaining:.2f}"]
    for index,line in enumerate(lines): page.drawString(65,730-index*30,line)
    page.setStrokeColorRGB(.1,.35,.75); page.line(60,470,535,470)
    page.setFont("Helvetica-Oblique",9); page.drawString(60,445,"Document généré par le système de gestion scolaire.")
    page.save(); buffer.seek(0)
    return send_file(buffer,mimetype="application/pdf",as_attachment=True,download_name=f"recu-{payment_id}.pdf")


@app.route("/payments", methods=["GET", "POST"])
@login_required("admin", "accountant", "parent", "director")
def payments():
    db=get_db()
    if request.method == "POST":
        if session.get("role") == "parent": abort(403)
        try:
            student_id=int(request.form["student_id"]); amount=float(request.form["amount"])
            method=request.form["method"].strip()
            student=db.execute("SELECT parent_name,parent_phone,parent_user_id,first_name,last_name,school_year FROM students WHERE id=? AND active=1",(student_id,)).fetchone()
            allowed_methods = ("Espèces", "Virement", "Virement bancaire", "Mobile money", "Flouci / e-Dinar", "Chèque", "Carte bancaire")
            if not math.isfinite(amount) or amount <= 0 or method not in allowed_methods or not student: raise ValueError
            paid_at = datetime.now().isoformat(timespec="minutes")
            db.execute("INSERT INTO payments(student_id,amount,paid_at,method,reference,school_year,created_by) VALUES(?,?,?,?,?,?,?)", (student_id,amount,paid_at,method,request.form.get("reference", "").strip(),student["school_year"],session["user_id"]))
            new_pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
            due = db.execute("SELECT COALESCE(SUM(amount),0) FROM fee_schedules WHERE school_year=?", (student["school_year"],)).fetchone()[0]
            paid = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE student_id=? AND school_year=?", (student_id, student["school_year"])).fetchone()[0]
            remaining = max(0, due - paid)
            receipt_link = url_for("payment_receipt", payment_id=new_pid)
            msg = f"Paiement de {amount:.2f} enregistré le {paid_at} par {method}. Solde restant : {remaining:.2f}. Reçu : {receipt_link}"
            db.execute("INSERT INTO notifications(user_id,channel,message,status,created_at) VALUES(?,'internal',?,?,?)", (student["parent_user_id"], msg, "queued", paid_at))
            db.commit()
            flash("Paiement enregistré. Le reçu PDF est disponible dans l'historique.", "success")
        except (ValueError, KeyError): flash("Paiement invalide : contrôle l'élève, le montant et le mode.", "danger")
        return redirect(url_for("payments"))
    if session.get("role") == "parent":
        rows=db.execute("SELECT p.*,s.first_name,s.last_name FROM payments p JOIN students s ON s.id=p.student_id WHERE s.parent_user_id=? ORDER BY paid_at DESC",(session["user_id"],)).fetchall()
        students=[]
    else:
        rows=db.execute("SELECT p.*,s.first_name,s.last_name FROM payments p JOIN students s ON s.id=p.student_id ORDER BY paid_at DESC").fetchall()
        students=db.execute("SELECT * FROM students WHERE active=1 ORDER BY last_name").fetchall()
    return render_template("payments.html", payments=rows, students=students)

@app.route("/payments/export.csv")
@login_required("admin", "accountant")
def payments_export():
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Eleve", "Classe", "Montant", "Mode", "Reference", "Annee_Scolaire", "Enregistre_Par"])
    sql = """
        SELECT p.id, p.paid_at, s.first_name || ' ' || s.last_name AS student_name,
               COALESCE(c.name, 'Sans classe') AS class_name, p.amount, p.method, p.reference,
               p.school_year, COALESCE(u.username, 'Système') AS created_by_name
        FROM payments p
        JOIN students s ON s.id=p.student_id
        LEFT JOIN classes c ON c.id=s.class_id
        LEFT JOIN users u ON u.id=p.created_by
        ORDER BY p.paid_at DESC
    """
    rows = get_db().execute(sql).fetchall()
    writer.writerows([tuple(row) for row in rows])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=paiements_comptabilite.csv"
    return response


@app.route("/payments/send-reminders", methods=["POST"])
@login_required("admin", "accountant")
def payments_send_reminders():
    db = get_db()
    year = "2026-2027"
    due_total = db.execute("SELECT COALESCE(SUM(amount), 0) FROM fee_schedules WHERE school_year=?", (year,)).fetchone()[0]
    students = db.execute(
        "SELECT s.id, s.first_name, s.last_name, s.parent_user_id, "
        "(SELECT COALESCE(SUM(amount),0) FROM payments WHERE student_id=s.id AND school_year=?) as paid "
        "FROM students s WHERE s.active=1 AND s.school_year=?",
        (year, year)
    ).fetchall()
    sent_count = 0
    now_str = datetime.now().isoformat(timespec="minutes")
    for st in students:
        remaining = max(0, due_total - st["paid"])
        if remaining > 0 and st["parent_user_id"]:
            msg = f"Rappel : Solde de scolarité restant de {remaining:.2f} pour votre enfant {st['first_name']} {st['last_name']} (Année {year}). Merci de régulariser."
            db.execute("INSERT INTO notifications(user_id, channel, message, status, created_at) VALUES(?,'internal',?,?,?)",
                       (st["parent_user_id"], msg, "queued", now_str))
            sent_count += 1
    db.commit()
    flash(f"{sent_count} rappel(s) d'impayé envoyé(s) avec succès aux parents concernés.", "success")
    return redirect(url_for("payments"))


@app.route("/payments/<int:payment_id>/edit", methods=["GET", "POST"])
@login_required("admin", "accountant")
def payment_edit(payment_id):
    db = get_db()
    payment = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        abort(404)
    students = db.execute("SELECT * FROM students WHERE active=1 ORDER BY last_name").fetchall()
    if request.method == "POST":
        try:
            student_id = int(request.form["student_id"])
            amount = float(request.form["amount"])
            method = request.form["method"]
            student = db.execute("SELECT id, school_year FROM students WHERE id=? AND active=1", (student_id,)).fetchone()
            if not math.isfinite(amount) or amount <= 0 or method not in ("Espèces", "Virement", "Mobile money") or not student:
                raise ValueError
            old_vals = {"student_id": payment["student_id"], "amount": payment["amount"], "method": payment["method"]}
            db.execute("UPDATE payments SET student_id=?, amount=?, method=?, reference=?, school_year=? WHERE id=?",
                       (student_id, amount, method, request.form.get("reference", "").strip(), student["school_year"], payment_id))
            audit("update", "payment", payment_id, old_vals, {"student_id": student_id, "amount": amount, "method": method})
            db.commit()
            flash("Paiement mis à jour.", "success")
            return redirect(url_for("payments"))
        except (ValueError, KeyError):
            flash("Informations de paiement invalides.", "danger")
    return render_template("payment_form.html", payment=payment, students=students)


@app.route("/payments/<int:payment_id>/delete", methods=["POST"])
@login_required("admin", "accountant")
def payment_delete(payment_id):
    db = get_db()
    payment = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        abort(404)
    db.execute("DELETE FROM payments WHERE id=?", (payment_id,))
    audit("delete", "payment", payment_id, {"student_id": payment["student_id"], "amount": payment["amount"]})
    db.commit()
    flash("Paiement supprimé.", "success")
    return redirect(url_for("payments"))


@app.route("/homework", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student", "director", "secretary")
def homework():
    db=get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin","teacher","director"): abort(403)
        try:
            subject_id=int(request.form["subject_id"]); class_id=int(request.form["class_id"])
            school_class=db.execute("SELECT level,school_year FROM classes WHERE id=?",(class_id,)).fetchone()
            subject=db.execute("SELECT level,school_year FROM subjects WHERE id=? AND active=1",(subject_id,)).fetchone()
            if not school_class or not subject or subject["level"]!=school_class["level"] or subject["school_year"]!=school_class["school_year"]: raise ValueError
            if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?",(session["user_id"],class_id,subject_id,school_class["school_year"])).fetchone(): abort(403)
            due_date = parse_iso_date(request.form["due_date"])
            if due_date < date.today():
                raise ValueError("La date limite du devoir est déjà passée.")
            title = request.form.get("title", "").strip()
            if not title:
                raise ValueError("Le titre est obligatoire.")
            attachment = save_upload(request.files.get("attachment"))
            db.execute("INSERT INTO homework(title,description,subject_id,class_id,teacher_id,due_date,attachment_path,school_year) VALUES(?,?,?,?,?,?,?,?)", (title,request.form.get("description", "").strip(),subject_id,class_id,session["user_id"],due_date.isoformat(),attachment,school_class["school_year"]))
            db.commit(); flash("Devoir publié.","success")
        except (ValueError,KeyError): flash("Vérifie les informations du devoir et le type de fichier joint.","danger")
        return redirect(url_for("homework"))
    if session.get("role") == "parent":
        rows=db.execute("SELECT h.*,s.name subject_name,c.name class_name,u.username teacher_name FROM homework h JOIN subjects s ON s.id=h.subject_id JOIN classes c ON c.id=h.class_id JOIN users u ON u.id=h.teacher_id WHERE h.active=1 AND EXISTS(SELECT 1 FROM students st WHERE st.class_id=h.class_id AND st.parent_user_id=?) ORDER BY h.due_date",(session["user_id"],)).fetchall()
    elif session.get("role") == "student":
        rows=db.execute("SELECT h.*,s.name subject_name,c.name class_name,u.username teacher_name FROM homework h JOIN subjects s ON s.id=h.subject_id JOIN classes c ON c.id=h.class_id JOIN users u ON u.id=h.teacher_id WHERE h.active=1 AND h.class_id IN (SELECT class_id FROM students WHERE student_user_id=?) ORDER BY h.due_date",(session["user_id"],)).fetchall()
    elif session.get("role") == "teacher":
        rows=db.execute("SELECT h.*,s.name subject_name,c.name class_name,u.username teacher_name FROM homework h JOIN subjects s ON s.id=h.subject_id JOIN classes c ON c.id=h.class_id JOIN users u ON u.id=h.teacher_id WHERE h.active=1 AND EXISTS(SELECT 1 FROM teacher_assignments a WHERE a.teacher_id=? AND a.class_id=h.class_id AND a.subject_id=h.subject_id) ORDER BY h.due_date",(session["user_id"],)).fetchall()
    else:
        rows=db.execute("SELECT h.*,s.name subject_name,c.name class_name,u.username teacher_name FROM homework h JOIN subjects s ON s.id=h.subject_id JOIN classes c ON c.id=h.class_id JOIN users u ON u.id=h.teacher_id WHERE h.active=1 ORDER BY h.due_date").fetchall()
    submissions={}
    if session.get("role")=="student":
        student=db.execute("SELECT id FROM students WHERE student_user_id=?",(session["user_id"],)).fetchone()
        if student:
            submissions={row["homework_id"]:row for row in db.execute("SELECT * FROM submissions WHERE student_id=?",(student["id"],)).fetchall()}
    if session.get("role")=="parent":
        submission_list=db.execute("SELECT sub.*,s.first_name,s.last_name FROM submissions sub JOIN students s ON s.id=sub.student_id WHERE s.parent_user_id=? ORDER BY sub.submitted_at DESC",(session["user_id"],)).fetchall()
    elif session.get("role")=="teacher":
        submission_list=db.execute("SELECT sub.*,s.first_name,s.last_name FROM submissions sub JOIN students s ON s.id=sub.student_id JOIN homework h ON h.id=sub.homework_id WHERE EXISTS(SELECT 1 FROM teacher_assignments a WHERE a.teacher_id=? AND a.class_id=h.class_id AND a.subject_id=h.subject_id) ORDER BY sub.submitted_at DESC",(session["user_id"],)).fetchall()
    elif session.get("role") in ("admin", "director", "secretary"):
        submission_list=db.execute("SELECT sub.*,s.first_name,s.last_name FROM submissions sub JOIN students s ON s.id=sub.student_id ORDER BY sub.submitted_at DESC").fetchall()
    else:
        submission_list=[]
    return render_template("homework.html", homework=rows, submissions=submissions, submission_list=submission_list,
        subjects=db.execute("SELECT * FROM subjects WHERE active=1 AND (?<>'teacher' OR id IN (SELECT subject_id FROM teacher_assignments WHERE teacher_id=?))",(session.get("role"),session["user_id"])).fetchall(),
        classes=db.execute("SELECT * FROM classes WHERE (?<>'teacher' OR id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?))",(session.get("role"),session["user_id"])).fetchall())


@app.route("/homework/<int:homework_id>/submit",methods=["POST"])
@login_required("student")
def homework_submit(homework_id):
    db=get_db(); work=db.execute("SELECT due_date,class_id FROM homework WHERE id=? AND active=1",(homework_id,)).fetchone()
    student=db.execute("SELECT id,class_id FROM students WHERE student_user_id=? AND active=1",(session["user_id"],)).fetchone()
    if not work or not student or student["class_id"]!=work["class_id"]: abort(403)
    if datetime.now().date().isoformat()>work["due_date"]: abort(400,description="La date limite de dépôt est dépassée.")
    try:
        stored=save_upload(request.files.get("file"))
        if not stored: raise ValueError
        db.execute("INSERT INTO submissions(homework_id,student_id,file_path,submitted_at) VALUES(?,?,?,?) ON CONFLICT(homework_id,student_id) DO UPDATE SET file_path=excluded.file_path,submitted_at=excluded.submitted_at",(homework_id,student["id"],stored,datetime.now().isoformat(timespec="minutes")))
        db.commit(); flash("Travail déposé.","success")
    except ValueError:
        flash("Ajoute un fichier PDF, image ou document autorisé.","danger")
    return redirect(url_for("homework"))


@app.route("/homework/<int:homework_id>/correction",methods=["POST"])
@login_required("admin", "teacher")
def homework_correction(homework_id):
    db=get_db(); work=db.execute("SELECT class_id,subject_id,due_date FROM homework WHERE id=?",(homework_id,)).fetchone()
    if not work: abort(404)
    if datetime.now().date().isoformat()<work["due_date"]: abort(400,description="La correction ne peut être publiée qu'après la date de remise.")
    if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?",(session["user_id"],work["class_id"],work["subject_id"])).fetchone(): abort(403)
    try:
        stored=save_upload(request.files.get("file"))
        if not stored: raise ValueError
        db.execute("UPDATE homework SET correction_path=? WHERE id=?",(stored,homework_id)); db.commit(); flash("Correction mise à disposition.","success")
    except ValueError: flash("Fichier de correction invalide.","danger")
    return redirect(url_for("homework"))


@app.route("/submissions/<int:submission_id>/file")
@login_required("admin", "teacher", "parent", "student")
def submission_file(submission_id):
    db=get_db(); row=db.execute("SELECT sub.file_path,sub.student_id,s.parent_user_id,s.student_user_id,s.class_id,h.subject_id FROM submissions sub JOIN students s ON s.id=sub.student_id JOIN homework h ON h.id=sub.homework_id WHERE sub.id=?",(submission_id,)).fetchone()
    if not row: abort(404)
    role=session.get("role")
    if role=="parent" and row["parent_user_id"]!=session["user_id"]: abort(403)
    if role=="student" and row["student_user_id"]!=session["user_id"]: abort(403)
    if role=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?",(session["user_id"],row["class_id"],row["subject_id"])).fetchone(): abort(403)
    path=Path(app.config["UPLOAD_FOLDER"])/row["file_path"]
    if not path.is_file(): abort(404)
    return send_file(path,as_attachment=True,download_name=path.name)


@app.route("/submissions/<int:submission_id>/grade",methods=["POST"])
@login_required("admin", "teacher")
def submission_grade(submission_id):
    db=get_db(); row=db.execute("SELECT sub.homework_id,h.class_id,h.subject_id FROM submissions sub JOIN homework h ON h.id=sub.homework_id WHERE sub.id=?",(submission_id,)).fetchone()
    if not row: abort(404)
    if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?",(session["user_id"],row["class_id"],row["subject_id"])).fetchone(): abort(403)
    try:
        score=float(request.form["score"])
        if not math.isfinite(score) or score<0 or score>20: raise ValueError
        db.execute("UPDATE submissions SET score=?,comment=? WHERE id=?",(score,request.form.get("comment","").strip(),submission_id)); db.commit(); flash("Travail corrigé et noté.","success")
    except (ValueError,KeyError): flash("La note doit être comprise entre 0 et 20.","danger")
    return redirect(url_for("homework"))


@app.route("/homework/files/<int:homework_id>/<kind>")
@login_required("admin", "teacher", "parent", "student")
def homework_file(homework_id, kind):
    if kind not in ("attachment", "correction"): abort(404)
    db=get_db()
    work=db.execute(f"SELECT h.{kind}_path AS file_path,h.class_id,h.subject_id,h.teacher_id,h.due_date FROM homework h WHERE h.id=? AND h.active=1",(homework_id,)).fetchone()
    if not work or not work["file_path"]: abort(404)
    if kind=="correction" and datetime.now().date().isoformat()<work["due_date"]: abort(403)
    role=session.get("role")
    if role=="parent" and not db.execute("SELECT 1 FROM students WHERE parent_user_id=? AND class_id=?",(session["user_id"],work["class_id"])).fetchone(): abort(403)
    if role=="student" and not db.execute("SELECT 1 FROM students WHERE student_user_id=? AND class_id=?",(session["user_id"],work["class_id"])).fetchone(): abort(403)
    if role=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?",(session["user_id"],work["class_id"],work["subject_id"])).fetchone(): abort(403)
    path=Path(app.config["UPLOAD_FOLDER"]) / work["file_path"]
    if not path.is_file(): abort(404)
    return send_file(path,as_attachment=True,download_name=path.name)

@app.route("/homework/<int:homework_id>/edit", methods=["GET", "POST"])
@login_required("admin", "teacher", "director")
def homework_edit(homework_id):
    db = get_db()
    work = db.execute("SELECT * FROM homework WHERE id=? AND active=1", (homework_id,)).fetchone()
    if not work:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?", (session["user_id"], work["class_id"], work["subject_id"])).fetchone():
        abort(403)
    classes = db.execute("SELECT * FROM classes WHERE (?<>'teacher' OR id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?))", (session.get("role"), session["user_id"])).fetchall()
    subjects = db.execute("SELECT * FROM subjects WHERE active=1 AND (?<>'teacher' OR id IN (SELECT subject_id FROM teacher_assignments WHERE teacher_id=?))", (session.get("role"), session["user_id"])).fetchall()
    if request.method == "POST":
        try:
            subject_id = int(request.form["subject_id"])
            class_id = int(request.form["class_id"])
            title = request.form.get("title", "").strip()
            if not title:
                raise ValueError("Le titre est obligatoire.")
            school_class = db.execute("SELECT level, school_year FROM classes WHERE id=?", (class_id,)).fetchone()
            subject = db.execute("SELECT level, school_year FROM subjects WHERE id=? AND active=1", (subject_id,)).fetchone()
            if not school_class or not subject or subject["level"] != school_class["level"] or subject["school_year"] != school_class["school_year"]:
                raise ValueError("La matière et la classe doivent appartenir au même niveau et à la même année scolaire.")
            if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?", (session["user_id"], class_id, subject_id, school_class["school_year"])).fetchone():
                abort(403)
            due_date = parse_iso_date(request.form["due_date"])
            if due_date < date.today():
                raise ValueError("La date limite du devoir ne peut pas être dans le passé.")
            attachment = save_upload(request.files.get("attachment")) or work["attachment_path"]
            old_vals = {"title": work["title"], "due_date": work["due_date"]}
            db.execute("UPDATE homework SET title=?, description=?, subject_id=?, class_id=?, due_date=?, attachment_path=? WHERE id=?",
                       (title, request.form.get("description", "").strip(), subject_id, class_id, due_date.isoformat(), attachment, homework_id))
            audit("update", "homework", homework_id, old_vals, {"title": title, "due_date": due_date.isoformat()})
            db.commit()
            flash("Devoir mis à jour.", "success")
            return redirect(url_for("homework"))
        except (ValueError, KeyError) as e:
            flash(str(e) if str(e) else "Vérifie les informations du devoir.", "danger")
    return render_template("homework_form.html", homework=work, classes=classes, subjects=subjects)


@app.route("/homework/<int:homework_id>/delete", methods=["POST"])
@login_required("admin", "teacher", "director")
def homework_delete(homework_id):
    db = get_db()
    work = db.execute("SELECT * FROM homework WHERE id=? AND active=1", (homework_id,)).fetchone()
    if not work:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND subject_id=?", (session["user_id"], work["class_id"], work["subject_id"])).fetchone():
        abort(403)
    db.execute("UPDATE homework SET active=0 WHERE id=?", (homework_id,))
    audit("delete", "homework", homework_id, {"title": work["title"]})
    db.commit()
    flash("Devoir supprimé.", "success")
    return redirect(url_for("homework"))


@app.route("/messages", methods=["GET", "POST"])
@login_required()
def messages():
    db = get_db()
    if request.method == "POST":
        recipient = request.form.get("recipient_id")
        try:
            recipient_id = int(recipient) if recipient else 0
        except ValueError:
            recipient_id = 0
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        is_draft = 1 if request.form.get("action") == "draft" else 0
        if not recipient_id or not subject or not body:
            flash("Destinataire, sujet et message sont obligatoires.", "danger")
        elif not can_message(session["user_id"], session["role"], recipient_id):
            flash("Ce destinataire n'est pas autorisé pour votre rôle ou vos affectations.", "danger")
        else:
            attachment = ""
            if "attachment" in request.files:
                try:
                    attachment = save_upload(request.files.get("attachment"))
                except ValueError as e:
                    flash(str(e), "danger")
                    return redirect(url_for("messages"))
            sent_at = datetime.now().isoformat(timespec="minutes")
            db.execute(
                "INSERT INTO messages(sender_id, recipient_id, subject, body, sent_at, is_draft, attachment_path) VALUES(?,?,?,?,?,?,?)",
                (session["user_id"], recipient_id, subject, body, sent_at, is_draft, attachment)
            )
            # If not draft, notify recipient
            if not is_draft:
                db.execute(
                    "INSERT INTO notifications(user_id, channel, message, status, created_at) VALUES(?,'internal',?,?,?)",
                    (recipient_id, f"Nouveau message reçu de {session.get('username')}: {subject}", "queued", sent_at)
                )
            db.commit()
            flash("Brouillon enregistré." if is_draft else "Message envoyé avec succès.", "success")
            return redirect(url_for("messages"))

    # Active messages (exclude drafts of others, exclude hidden messages)
    rows = db.execute(
        "SELECT m.*, a.username sender_name, b.username recipient_name FROM messages m "
        "JOIN users a ON a.id=m.sender_id JOIN users b ON b.id=m.recipient_id "
        "WHERE (m.sender_id=? AND m.hidden_by_sender=0) OR (m.recipient_id=? AND m.is_draft=0 AND m.hidden_by_recipient=0) "
        "ORDER BY m.sent_at DESC",
        (session["user_id"], session["user_id"])
    ).fetchall()

    users = [user for user in db.execute("SELECT id, username, role FROM users WHERE id<>? AND active=1 ORDER BY username", (session["user_id"],)).fetchall() if can_message(session["user_id"], session["role"], user["id"])]
    return render_template("messages.html", messages=rows, users=users)


@app.route("/messages/<int:message_id>/hide", methods=["POST"])
@login_required()
def message_hide(message_id):
    db = get_db()
    msg = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not msg:
        abort(404)
    user_id = session["user_id"]
    if msg["recipient_id"] == user_id:
        db.execute("UPDATE messages SET hidden_by_recipient=1 WHERE id=?", (message_id,))
        db.commit()
        flash("Message masqué de votre boîte.", "success")
    elif msg["sender_id"] == user_id and msg["is_draft"] == 1:
        # Sender can delete their draft
        db.execute("DELETE FROM messages WHERE id=?", (message_id,))
        db.commit()
        flash("Brouillon supprimé.", "success")
    elif msg["sender_id"] == user_id:
        db.execute("UPDATE messages SET hidden_by_sender=1 WHERE id=?", (message_id,))
        db.commit()
        flash("Message masqué de vos éléments envoyés.", "success")
    else:
        abort(403)
    return redirect(url_for("messages"))


@app.route("/messages/<int:message_id>/send-draft", methods=["POST"])
@login_required()
def message_send_draft(message_id):
    db = get_db()
    msg = db.execute("SELECT * FROM messages WHERE id=? AND sender_id=? AND is_draft=1", (message_id, session["user_id"])).fetchone()
    if not msg:
        abort(404)
    sent_at = datetime.now().isoformat(timespec="minutes")
    db.execute("UPDATE messages SET is_draft=0, sent_at=? WHERE id=?", (sent_at, message_id))
    db.execute(
        "INSERT INTO notifications(user_id, channel, message, status, created_at) VALUES(?,'internal',?,?,?)",
        (msg["recipient_id"], f"Nouveau message reçu de {session.get('username')}: {msg['subject']}", "queued", sent_at)
    )
    db.commit()
    flash("Brouillon envoyé avec succès.", "success")
    return redirect(url_for("messages"))


@app.route("/messages/<int:message_id>/attachment")
@login_required()
def message_attachment(message_id):
    db = get_db()
    msg = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not msg or not msg["attachment_path"]:
        abort(404)
    if session["user_id"] not in (msg["sender_id"], msg["recipient_id"]):
        abort(403)
    path = Path(app.config["UPLOAD_FOLDER"]) / msg["attachment_path"]
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.route("/pre-enrollment", methods=["GET", "POST"])
def pre_enrollment():
    if request.method == "POST":
        values=[request.form.get(k,"").strip() for k in ("first_name","last_name","parent_name")]
        birth_date=request.form.get("birth_date","").strip()
        if not all(values): flash("Prénom, nom de l'enfant et nom du parent sont obligatoires.","danger")
        elif not is_valid_birth_date(birth_date): flash("La date de naissance doit être valide et ne peut pas être dans le futur.","danger")
        else:
            db=get_db(); db.execute("INSERT INTO pre_enrollments(first_name,last_name,birth_date,parent_name,parent_email,parent_phone,created_at) VALUES(?,?,?,?,?,?,?)",(values[0],values[1],birth_date,values[2],request.form.get("parent_email",""),request.form.get("parent_phone",""),datetime.now().isoformat(timespec="minutes")))
            db.commit(); flash("Demande de pré-inscription envoyée à l'administration.","success")
    return render_template("pre_enrollment.html")


@app.route("/pre-enrollments", methods=["GET", "POST"])
@login_required("admin", "secretary")
def pre_enrollments():
    db=get_db()
    if request.method=="POST":
        application_id=int(request.form.get("application_id",0)); action=request.form.get("action")
        application=db.execute("SELECT * FROM pre_enrollments WHERE id=? AND status='pending'",(application_id,)).fetchone()
        if not application or action not in ("approve","reject"):
            flash("Demande introuvable ou déjà traitée.","warning")
        elif action=="approve":
            class_id=request.form.get("class_id") or None
            if class_id:
                room=db.execute("SELECT capacity,school_year,(SELECT COUNT(*) FROM students WHERE class_id=? AND school_year='2026-2027' AND active=1) AS count FROM classes WHERE id=?",(class_id,class_id)).fetchone()
                if not room or room["school_year"]!="2026-2027" or room["count"]>=room["capacity"]:
                    flash("Classe invalide ou capacité maximale atteinte.","danger")
                    return redirect(url_for("pre_enrollments"))
            db.execute("INSERT INTO students(first_name,last_name,birth_date,parent_name,parent_phone,class_id,school_year) VALUES(?,?,?,?,?,?,?)",(application["first_name"],application["last_name"],application["birth_date"],application["parent_name"],application["parent_phone"],class_id,"2026-2027"))
            db.execute("UPDATE pre_enrollments SET status='approved' WHERE id=?",(application_id,)); db.commit(); flash("Demande approuvée et dossier élève créé.","success")
        else:
            db.execute("UPDATE pre_enrollments SET status='rejected' WHERE id=?",(application_id,)); db.commit(); flash("Demande refusée.","success")
        return redirect(url_for("pre_enrollments"))
    return render_template("pre_enrollments.html",applications=db.execute("SELECT * FROM pre_enrollments ORDER BY created_at DESC").fetchall(),classes=db.execute("SELECT * FROM classes ORDER BY name").fetchall())


@app.route("/fee-schedules", methods=["GET", "POST"])
@login_required("admin", "accountant", "director")
def fee_schedules():
    db=get_db()
    if request.method == "POST":
        try:
            label=request.form["label"].strip(); amount=float(request.form["amount"])
            due_date=request.form.get("due_date","").strip()
            if due_date:
                due_date=parse_iso_date(due_date).isoformat()
            if not label or not math.isfinite(amount) or amount <= 0: raise ValueError
            db.execute("INSERT INTO fee_schedules(label,amount,due_date,school_year) VALUES(?,?,?,?)",(label,amount,due_date,request.form.get("school_year","2026-2027").strip()))
            db.commit(); flash("Tarif scolaire ajouté.","success")
        except (ValueError,KeyError): flash("Vérifie le libellé et le montant.","danger")
        return redirect(url_for("fee_schedules"))
    return render_template("fee_schedules.html", fees=db.execute("SELECT * FROM fee_schedules ORDER BY school_year DESC,due_date").fetchall())

@app.route("/fee-schedules/<int:fee_id>/edit", methods=["GET", "POST"])
@login_required("admin", "accountant", "director")
def fee_edit(fee_id):
    db = get_db()
    fee = db.execute("SELECT * FROM fee_schedules WHERE id=?", (fee_id,)).fetchone()
    if not fee:
        abort(404)
    if request.method == "POST":
        try:
            label = request.form["label"].strip()
            amount = float(request.form["amount"])
            due_date = request.form.get("due_date", "").strip()
            if due_date:
                due_date = parse_iso_date(due_date).isoformat()
            year = request.form.get("school_year", "2026-2027").strip()
            if not label or not math.isfinite(amount) or amount <= 0:
                raise ValueError
            old_vals = {"label": fee["label"], "amount": fee["amount"], "due_date": fee["due_date"]}
            db.execute("UPDATE fee_schedules SET label=?, amount=?, due_date=?, school_year=? WHERE id=?",
                       (label, amount, due_date, year, fee_id))
            audit("update", "fee_schedule", fee_id, old_vals, {"label": label, "amount": amount})
            db.commit()
            flash("Tarif mis à jour.", "success")
            return redirect(url_for("fee_schedules"))
        except (ValueError, KeyError):
            flash("Vérifie le libellé et le montant.", "danger")
    return render_template("fee_schedule_form.html", fee=fee)


@app.route("/fee-schedules/<int:fee_id>/delete", methods=["POST"])
@login_required("admin", "accountant", "director")
def fee_delete(fee_id):
    db = get_db()
    fee = db.execute("SELECT * FROM fee_schedules WHERE id=?", (fee_id,)).fetchone()
    if not fee:
        abort(404)
    db.execute("DELETE FROM fee_schedules WHERE id=?", (fee_id,))
    audit("delete", "fee_schedule", fee_id, {"label": fee["label"], "amount": fee["amount"]})
    db.commit()
    flash("Tarif supprimé.", "success")
    return redirect(url_for("fee_schedules"))


@app.route("/users", methods=["GET", "POST"])
@login_required("admin")
def users():
    db=get_db()
    if request.method == "POST":
        username=request.form.get("username","").strip()
        full_name=request.form.get("full_name","").strip()
        password=request.form.get("password","")
        role=request.form.get("role","")
        if role not in ("teacher", "parent", "accountant", "secretary", "student", "director", "admin") or not username or not password or len(password) < 8:
            flash("Rôle invalide ou champs incomplets (mot de passe : 8 caractères minimum).", "danger")
        else:
            try:
                db.execute("INSERT INTO users(username,password_hash,role,full_name,email) VALUES(?,?,?,?,?)",(username,generate_password_hash(password),role,full_name,request.form.get("email","").strip()))
                db.commit(); flash("Compte utilisateur créé.","success"); return redirect(url_for("users"))
            except sqlite3.IntegrityError:
                flash("Cet identifiant est déjà utilisé.","danger")
    rows=db.execute("SELECT id,username,role,full_name,email,active FROM users ORDER BY role,username").fetchall()
    return render_template("users.html", users=rows)


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required("admin")
def user_toggle(user_id):
    db=get_db()
    target=db.execute("SELECT id,role,active FROM users WHERE id=?",(user_id,)).fetchone()
    if not target: abort(404)
    if target["active"] and target["id"]==session["user_id"]:
        flash("Vous ne pouvez pas désactiver votre propre compte.","danger")
    elif target["active"] and target["role"]=="admin" and db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:
        flash("Impossible de désactiver le dernier administrateur actif.","danger")
    else:
        new_active=0 if target["active"] else 1
        db.execute("UPDATE users SET active=? WHERE id=?",(new_active,user_id))
        audit("activate" if new_active else "deactivate","user",user_id,{"active":target["active"]},{"active":new_active})
        db.commit()
        flash("Compte réactivé." if new_active else "Compte désactivé; ses sessions seront révoquées à la prochaine requête.","success")
    return redirect(url_for("users"))

@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def user_edit(user_id):
    db = get_db()
    user = db.execute("SELECT id, username, role, full_name, email, active FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        new_password = request.form.get("new_password", "").strip()
        new_role = request.form.get("role", user["role"])
        if not full_name:
            flash("Le nom complet est obligatoire.", "danger")
            return render_template("user_form.html", user=user)
        if new_password and len(new_password) < 8:
            flash("Le nouveau mot de passe doit comporter au moins 8 caractères.", "danger")
            return render_template("user_form.html", user=user)
        old_vals = {"full_name": user["full_name"], "email": user["email"], "role": user["role"]}
        if new_password:
            db.execute("UPDATE users SET full_name=?, email=?, role=?, password_hash=? WHERE id=?",
                       (full_name, email, new_role, generate_password_hash(new_password), user_id))
        else:
            db.execute("UPDATE users SET full_name=?, email=?, role=? WHERE id=?",
                       (full_name, email, new_role, user_id))
        audit("update", "user", user_id, old_vals, {"full_name": full_name, "email": email, "role": new_role})
        db.commit()
        flash("Utilisateur mis à jour.", "success")
        return redirect(url_for("users"))
    return render_template("user_form.html", user=user)


@app.route("/profile")
@login_required()
def profile():
    user = get_db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return render_template("profile.html", user=user)


@app.route("/profile/info", methods=["POST"])
@login_required()
def profile_info():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    if not full_name:
        flash("Le nom complet ne peut pas être vide.", "danger")
    else:
        db = get_db()
        db.execute("UPDATE users SET full_name=?, email=? WHERE id=?", (full_name, email, session["user_id"]))
        db.commit()
        flash("Informations de profil mises à jour.", "success")
    return redirect(url_for("profile"))


@app.route("/profile/password", methods=["POST"])
@login_required()
def profile_password():
    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")
    db = get_db()
    user = db.execute("SELECT password_hash FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user or not check_password_hash(user["password_hash"], current_pw):
        flash("Mot de passe actuel incorrect.", "danger")
    elif len(new_pw) < 8:
        flash("Le nouveau mot de passe doit faire au moins 8 caractères.", "danger")
    elif new_pw != confirm_pw:
        flash("La confirmation du mot de passe ne correspond pas.", "danger")
    else:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), session["user_id"]))
        db.commit()
        flash("Mot de passe modifié avec succès.", "success")
    return redirect(url_for("profile"))


@app.route("/absences", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student", "secretary", "director")
def absences():
    db=get_db()
    if request.method == "POST":
        if session.get("role") in ("parent", "student"): abort(403)
        try:
            student_id=int(request.form["student_id"])
            student=db.execute("SELECT class_id,school_year FROM students WHERE id=? AND active=1",(student_id,)).fetchone()
            if not student: raise ValueError("Élève introuvable ou inactif.")
            if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND school_year=?",(session["user_id"],student["class_id"],student["school_year"])).fetchone(): abort(403)
            absence_date = parse_iso_date(request.form["absence_date"])
            if absence_date > date.today():
                raise ValueError("Une absence ne peut pas être dans le futur.")
            existing = db.execute("SELECT 1 FROM absences WHERE student_id=? AND absence_date=? AND school_year=?", (student_id, absence_date.isoformat(), student["school_year"])).fetchone()
            if existing:
                raise ValueError("Une absence a déjà été enregistrée pour cet élève à cette date.")
            db.execute("INSERT INTO absences(student_id,absence_date,reason,school_year) VALUES(?,?,?,?)",(student_id,absence_date.isoformat(),request.form.get("reason","").strip(),student["school_year"]))
            db.commit(); flash("Absence enregistrée.","success")
        except (ValueError,KeyError) as e:
            flash(str(e) if str(e) else "Vérifie les informations de l'absence.","danger")
        return redirect(url_for("absences"))
    if session.get("role") == "parent":
        rows=db.execute("SELECT a.*,s.first_name,s.last_name FROM absences a JOIN students s ON s.id=a.student_id WHERE s.parent_user_id=? ORDER BY absence_date DESC",(session["user_id"],)).fetchall()
    elif session.get("role") == "student":
        rows=db.execute("SELECT a.*,s.first_name,s.last_name FROM absences a JOIN students s ON s.id=a.student_id WHERE s.student_user_id=? ORDER BY absence_date DESC",(session["user_id"],)).fetchall()
    elif session.get("role") == "teacher":
        rows=db.execute("SELECT a.*,s.first_name,s.last_name FROM absences a JOIN students s ON s.id=a.student_id WHERE s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY absence_date DESC",(session["user_id"],)).fetchall()
    else:
        rows=db.execute("SELECT a.*,s.first_name,s.last_name FROM absences a JOIN students s ON s.id=a.student_id ORDER BY absence_date DESC").fetchall()
    students=db.execute("SELECT * FROM students WHERE active=1 AND (?<>'teacher' OR class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)) AND (?<>'student' OR student_user_id=?) ORDER BY last_name",(session.get("role"),session["user_id"],session.get("role"),session["user_id"])).fetchall()
    return render_template("absences.html", absences=rows, students=students)


@app.route("/absences/<int:absence_id>/justify", methods=["POST"])
@login_required("parent")
def absence_justify(absence_id):
    db=get_db()
    db.execute("UPDATE absences SET justified=1 WHERE id=? AND student_id IN (SELECT id FROM students WHERE parent_user_id=?)",(absence_id,session["user_id"]))
    db.commit(); flash("Absence marquée comme justifiée.","success")
    return redirect(url_for("absences"))

@app.route("/absences/<int:absence_id>/edit", methods=["GET", "POST"])
@login_required("admin", "teacher")
def absence_edit(absence_id):
    db = get_db()
    absence = db.execute("SELECT a.*, s.class_id, s.school_year FROM absences a JOIN students s ON s.id=a.student_id WHERE a.id=?", (absence_id,)).fetchone()
    if not absence:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND school_year=?", (session["user_id"], absence["class_id"], absence["school_year"])).fetchone():
        abort(403)
    students = db.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND (?<>'teacher' OR s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)) ORDER BY s.last_name", (session.get("role"), session["user_id"])).fetchall()
    if request.method == "POST":
        try:
            student_id = int(request.form["student_id"])
            absence_date = parse_iso_date(request.form["absence_date"])
            if absence_date > date.today():
                raise ValueError("Une absence ne peut pas être dans le futur.")
            justified = int(request.form.get("justified", 0))
            reason = request.form.get("reason", "").strip()
            old_vals = {"absence_date": absence["absence_date"], "reason": absence["reason"], "justified": absence["justified"]}
            db.execute("UPDATE absences SET student_id=?, absence_date=?, reason=?, justified=? WHERE id=?",
                       (student_id, absence_date.isoformat(), reason, justified, absence_id))
            audit("update", "absence", absence_id, old_vals, {"absence_date": absence_date.isoformat(), "justified": justified})
            db.commit()
            flash("Absence mise à jour.", "success")
            return redirect(url_for("absences"))
        except (ValueError, KeyError):
            flash("Informations d'absence invalides.", "danger")
    return render_template("absence_form.html", absence=absence, students=students)


@app.route("/absences/<int:absence_id>/delete", methods=["POST"])
@login_required("admin", "teacher")
def absence_delete(absence_id):
    db = get_db()
    absence = db.execute("SELECT a.*, s.class_id, s.school_year FROM absences a JOIN students s ON s.id=a.student_id WHERE a.id=?", (absence_id,)).fetchone()
    if not absence:
        abort(404)
    if session.get("role") == "teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND school_year=?", (session["user_id"], absence["class_id"], absence["school_year"])).fetchone():
        abort(403)
    db.execute("DELETE FROM absences WHERE id=?", (absence_id,))
    audit("delete", "absence", absence_id, {"student_id": absence["student_id"], "absence_date": absence["absence_date"]})
    db.commit()
    flash("Absence supprimée.", "success")
    return redirect(url_for("absences"))


@app.route("/students/export.csv")
@login_required("admin", "teacher", "accountant", "secretary")
def students_export():
    import csv, io
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["prenom","nom","date_naissance","parent","telephone","classe","annee_scolaire"])
    if session.get("role")=="teacher":
        rows=get_db().execute("SELECT s.first_name,s.last_name,s.birth_date,s.parent_name,s.parent_phone,c.name,s.school_year FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY s.last_name,s.first_name",(session["user_id"],)).fetchall()
    else:
        rows=get_db().execute("SELECT s.first_name,s.last_name,s.birth_date,s.parent_name,s.parent_phone,c.name,s.school_year FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 ORDER BY s.last_name,s.first_name").fetchall()
    writer.writerows([tuple(row) for row in rows])
    response=make_response("\\ufeff"+output.getvalue())
    response.headers["Content-Type"]="text/csv; charset=utf-8"
    response.headers["Content-Disposition"]="attachment; filename=eleves.csv"
    return response


@app.route("/assignments", methods=["GET", "POST"])
@login_required("admin")
def assignments():
    db=get_db()
    if request.method == "POST":
        try:
            teacher_id=int(request.form["teacher_id"]); subject_id=int(request.form["subject_id"]); class_id=int(request.form["class_id"]); year=request.form.get("school_year","2026-2027").strip()
            school_class=db.execute("SELECT level,school_year FROM classes WHERE id=?",(class_id,)).fetchone()
            subject=db.execute("SELECT level,school_year FROM subjects WHERE id=? AND active=1",(subject_id,)).fetchone()
            if not db.execute("SELECT id FROM users WHERE id=? AND role='teacher' AND active=1",(teacher_id,)).fetchone() or not school_class or not subject or school_class["school_year"]!=year or subject["school_year"]!=year or school_class["level"]!=subject["level"]: raise ValueError
            db.execute("INSERT INTO teacher_assignments(teacher_id,subject_id,class_id,school_year) VALUES(?,?,?,?)",(teacher_id,subject_id,class_id,year))
            db.commit(); flash("Affectation enregistrée.","success")
        except (ValueError,KeyError,sqlite3.IntegrityError): flash("Affectation invalide ou déjà existante.","danger")
        return redirect(url_for("assignments"))
    rows=db.execute("SELECT a.*,u.username teacher_name,s.name subject_name,c.name class_name FROM teacher_assignments a JOIN users u ON u.id=a.teacher_id JOIN subjects s ON s.id=a.subject_id JOIN classes c ON c.id=a.class_id ORDER BY c.name,s.name").fetchall()
    return render_template("assignments.html",assignments=rows,teachers=db.execute("SELECT * FROM users WHERE role='teacher' AND active=1").fetchall(),subjects=db.execute("SELECT * FROM subjects WHERE active=1").fetchall(),classes=db.execute("SELECT * FROM classes").fetchall())


@app.route("/assignments/<int:assignment_id>/delete",methods=["POST"])
@login_required("admin")
def assignment_delete(assignment_id):
    db=get_db()
    assignment=db.execute("SELECT * FROM teacher_assignments WHERE id=?",(assignment_id,)).fetchone()
    if not assignment: abort(404)
    related=db.execute("SELECT (SELECT COUNT(*) FROM timetable WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=?)+(SELECT COUNT(*) FROM homework WHERE teacher_id=? AND class_id=? AND subject_id=? AND school_year=? )",(assignment["teacher_id"],assignment["class_id"],assignment["subject_id"],assignment["school_year"],assignment["teacher_id"],assignment["class_id"],assignment["subject_id"],assignment["school_year"])).fetchone()[0]
    if related:
        flash("Cette affectation est utilisée par un emploi du temps ou des devoirs; retirez-les avant.","danger")
    else:
        db.execute("DELETE FROM teacher_assignments WHERE id=?",(assignment_id,)); db.commit()
        flash("Affectation supprimée.","success")
    return redirect(url_for("assignments"))


@app.route("/announcements", methods=["GET", "POST"])
@login_required("admin", "teacher", "parent", "student", "accountant", "secretary")
def announcements():
    db=get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin","teacher"): abort(403)
        title=request.form.get("title","").strip(); body=request.form.get("body","").strip()
        audience=request.form.get("audience","all")
        if not title or not body or audience not in ("all","parent","teacher","student"):
            flash("Titre, contenu ou audience invalide.","danger")
        else:
            db.execute("INSERT INTO announcements(title,body,audience,created_by,created_at) VALUES(?,?,?,?,?)",(title,body,audience,session["user_id"],datetime.now().isoformat(timespec="minutes")))
            db.commit(); flash("Annonce publiée.","success"); return redirect(url_for("announcements"))
    rows=db.execute("SELECT a.*,u.username author FROM announcements a JOIN users u ON u.id=a.created_by WHERE audience='all' OR audience=? ORDER BY created_at DESC",(session.get("role"),)).fetchall()
    return render_template("announcements.html",announcements=rows)


@app.route("/notifications")
@login_required()
def notifications():
    rows=get_db().execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",(session["user_id"],)).fetchall()
    return render_template("notifications.html",notifications=rows)


@app.route("/rooms", methods=["GET", "POST"])
@login_required("admin")
def rooms():
    db=get_db()
    if request.method == "POST":
        try:
            name=request.form["name"].strip(); capacity=int(request.form["capacity"]); year=request.form.get("school_year","2026-2027").strip()
            if not name or capacity<1 or not year: raise ValueError
            db.execute("INSERT INTO rooms(name,capacity,availability,school_year) VALUES(?,?,?,?)",(name,capacity,request.form.get("availability","").strip(),year)); db.commit(); flash("Salle enregistrée.","success")
        except (ValueError,KeyError): flash("Nom de salle et capacité valide requis.","danger")
        return redirect(url_for("rooms"))
    return render_template("rooms.html", rooms=db.execute("SELECT * FROM rooms WHERE active=1 ORDER BY name").fetchall())

@app.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def room_edit(room_id):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=? AND active=1", (room_id,)).fetchone()
    if not room:
        abort(404)
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            capacity = int(request.form["capacity"])
            year = request.form.get("school_year", "2026-2027").strip()
            avail = request.form.get("availability", "").strip()
            if not name or capacity < 1 or not year:
                raise ValueError
            assigned_max = db.execute("""
                SELECT MAX(c.capacity)
                FROM timetable t
                JOIN classes c ON c.id=t.class_id
                WHERE t.room_id=? AND t.school_year=?
            """, (room_id, year)).fetchone()[0]
            if assigned_max and capacity < assigned_max:
                flash(f"La capacité de la salle ({capacity}) ne peut pas être inférieure à la capacité de la classe qui y est programmée ({assigned_max} places).", "danger")
                return render_template("room_form.html", room=room)
            old_vals = {"name": room["name"], "capacity": room["capacity"], "availability": room["availability"]}
            db.execute("UPDATE rooms SET name=?, capacity=?, availability=?, school_year=? WHERE id=?",
                       (name, capacity, avail, year, room_id))
            audit("update", "room", room_id, old_vals, {"name": name, "capacity": capacity})
            db.commit()
            flash("Salle mise à jour.", "success")
            return redirect(url_for("rooms"))
        except (ValueError, KeyError):
            flash("Nom de salle et capacité valide requis.", "danger")
    return render_template("room_form.html", room=room)


@app.route("/rooms/<int:room_id>/delete", methods=["POST"])
@login_required("admin")
def room_delete(room_id):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        abort(404)
    referenced = db.execute("SELECT (SELECT COUNT(*) FROM timetable WHERE room_id=?)+(SELECT COUNT(*) FROM evaluations WHERE room_id=?)", (room_id, room_id)).fetchone()[0]
    if referenced:
        db.execute("UPDATE rooms SET active=0 WHERE id=?", (room_id,))
        flash("Salle archivée pour préserver l'historique de l'emploi du temps et des épreuves.", "warning")
    else:
        db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
        flash("Salle supprimée.", "success")
    audit("delete", "room", room_id, {"name": room["name"]})
    db.commit()
    return redirect(url_for("rooms"))


try:
    with app.app_context():
        init_db()
except Exception:
    pass

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
