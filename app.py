import os
import sqlite3
import json
import math
import secrets
import uuid
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
ALLOWED_UPLOADS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "odt"}


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
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description="Jeton de sécurité invalide. Rechargez la page et réessayez.")


@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'parent', 'accountant', 'secretary', 'student')),
            full_name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
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
            school_year TEXT NOT NULL DEFAULT '2026-2027'
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
        CREATE TABLE IF NOT EXISTS demo_seed (seed_key TEXT PRIMARY KEY, created_at TEXT NOT NULL);
    """)
    migrations = {
        "users": {"full_name": "TEXT DEFAULT ''", "email": "TEXT DEFAULT ''", "active": "INTEGER NOT NULL DEFAULT 1"},
        "students": {"medical_notes": "TEXT DEFAULT ''", "photo_path": "TEXT DEFAULT ''", "parent_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL", "student_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL"},
        "messages": {"is_draft": "INTEGER NOT NULL DEFAULT 0", "attachment_path": "TEXT DEFAULT ''", "hidden_by_sender": "INTEGER NOT NULL DEFAULT 0", "hidden_by_recipient": "INTEGER NOT NULL DEFAULT 0"},
    }
    for table, columns in migrations.items():
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for column, declaration in columns.items():
            if column not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    db.execute("UPDATE students SET student_user_id=NULL WHERE student_user_id IS NOT NULL AND id NOT IN (SELECT MIN(id) FROM students WHERE student_user_id IS NOT NULL GROUP BY student_user_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_student_user ON students(student_user_id) WHERE student_user_id IS NOT NULL")
    if not db.execute("SELECT id FROM users LIMIT 1").fetchone():
        db.execute("INSERT INTO users(username,password_hash,role,full_name) VALUES(?,?,?,?)",
                   ("admin", generate_password_hash("admin123"), "admin", "Administrateur"))
        db.execute("INSERT INTO users(username,password_hash,role,full_name) VALUES(?,?,?,?)",
                   ("comptable", generate_password_hash("compta123"), "accountant", "Aminata Diallo"))
    if not db.execute("SELECT 1 FROM demo_seed WHERE seed_key='school-demo-v2'").fetchone():
        legacy_demo = db.execute(
            "SELECT 1 FROM users WHERE username='enseignant' AND EXISTS(SELECT 1 FROM classes WHERE name='CP-A' AND school_year='2026-2027')"
        ).fetchone()
        if legacy_demo:
            db.execute("INSERT INTO demo_seed(seed_key,created_at) VALUES(?,?)", ("school-demo-v2", datetime.now().isoformat(timespec="seconds")))
        else:
            seed_demo_data(db)
    db.commit()
    db.close()


def seed_demo_data(db):
    """Populate an empty school database with fictional, linked demo records."""
    year = "2026-2027"
    today = datetime.now().date()
    users = [
        ("enseignant", "teacher", "Mamadou Ba", "enseignant@example.test", "prof123"),
        ("parent", "parent", "Fatou Ndiaye", "parent@example.test", "parent123"),
        ("parent2", "parent", "Ousmane Diop", "parent2@example.test", "parent123"),
        ("parent3", "parent", "Aissatou Sow", "parent3@example.test", "parent123"),
        ("eleve", "student", "Awa Ndiaye", "eleve@example.test", "eleve123"),
        ("eleve2", "student", "Cheikh Diop", "eleve2@example.test", "eleve123"),
        ("eleve3", "student", "Marième Sow", "eleve3@example.test", "eleve123"),
        ("secretaire", "secretary", "Mariama Fall", "secretariat@example.test", "secret123"),
    ]
    user_ids = {}
    for username, role, name, email, password in users:
        db.execute(
            "INSERT OR IGNORE INTO users(username,password_hash,role,full_name,email) VALUES(?,?,?,?,?)",
            (username, generate_password_hash(password), role, name, email),
        )
        user_ids[username] = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    admin_id = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()[0]
    accountant = db.execute("SELECT id FROM users WHERE role='accountant' ORDER BY id LIMIT 1").fetchone()[0]

    classes = []
    for name, level, section, capacity in (("CP-A", "CP", "A", 25), ("CE1-A", "CE1", "A", 25), ("CE2-A", "CE2", "A", 25)):
        classes.append(db.execute(
            "INSERT INTO classes(name,level,section,capacity,school_year) VALUES(?,?,?,?,?)",
            (name, level, section, capacity, year),
        ).lastrowid)
    subjects_by_level = {}
    for level, subjects in {
        "CP": (("Français", 2), ("Mathématiques", 2), ("Découverte du monde", 1)),
        "CE1": (("Français", 2), ("Mathématiques", 2), ("Sciences", 1)),
        "CE2": (("Français", 2), ("Mathématiques", 2), ("Histoire-géographie", 1)),
    }.items():
        for name, coefficient in subjects:
            subject_id = db.execute(
                "INSERT INTO subjects(name,coefficient,level,school_year) VALUES(?,?,?,?)",
                (name, coefficient, level, year),
            ).lastrowid
            subjects_by_level[(level, name)] = subject_id
    room_ids = [db.execute(
        "INSERT INTO rooms(name,capacity,availability,school_year) VALUES(?,?,?,?)",
        (name, 30, "Lundi-vendredi, 08:00-16:00", year),
    ).lastrowid for name in ("Salle 1", "Salle 2", "Bibliothèque")]

    students = []
    sample_students = [
        ("Awa", "Ndiaye", "2019-04-12", classes[0], user_ids["parent"], user_ids["eleve"]),
        ("Ibrahima", "Ndiaye", "2021-09-03", classes[0], user_ids["parent"], None),
        ("Fatou", "Ndiaye", "2020-06-19", classes[0], user_ids["parent"], None),
        ("Cheikh", "Diop", "2018-11-21", classes[1], user_ids["parent2"], user_ids["eleve2"]),
        ("Aminata", "Diop", "2019-03-07", classes[1], user_ids["parent2"], None),
        ("Marième", "Sow", "2017-07-08", classes[2], user_ids["parent3"], user_ids["eleve3"]),
        ("Moussa", "Sow", "2018-02-14", classes[2], user_ids["parent3"], None),
    ]
    for first, last, birth, class_id, parent_id, student_user_id in sample_students:
        parent_name = db.execute("SELECT full_name FROM users WHERE id=?", (parent_id,)).fetchone()[0]
        student_id = db.execute(
            "INSERT INTO students(first_name,last_name,birth_date,parent_name,parent_phone,parent_user_id,class_id,school_year,student_user_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (first, last, birth, parent_name, "+221 77 000 00 00", parent_id, class_id, year, student_user_id),
        ).lastrowid
        students.append((student_id, class_id))

    for class_id, level in zip(classes, ("CP", "CE1", "CE2")):
        subject_id = subjects_by_level[(level, "Français")]
        db.execute("INSERT INTO teacher_assignments(teacher_id,subject_id,class_id,school_year) VALUES(?,?,?,?)",
                   (user_ids["enseignant"], subject_id, class_id, year))
        db.execute("INSERT INTO timetable(class_id,teacher_id,subject_id,room_id,weekday,start_time,end_time,school_year) VALUES(?,?,?,?,?,?,?,?)",
                   (class_id, user_ids["enseignant"], subject_id, room_ids[classes.index(class_id) % len(room_ids)], 1 + classes.index(class_id), "08:00", "09:00", year))
        evaluation_id = db.execute("INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year) VALUES(?,?,?,?,?,?)",
                                   ("Évaluation de français - période 1", subject_id, class_id, today.isoformat(), 20, year)).lastrowid
        for student_id, student_class in students:
            if student_class == class_id:
                db.execute("INSERT INTO grades(evaluation_id,student_id,score,comment) VALUES(?,?,?,?)",
                           (evaluation_id, student_id, 15.5, "Très bon travail."))
        db.execute("INSERT INTO homework(title,description,subject_id,class_id,teacher_id,due_date,school_year) VALUES(?,?,?,?,?,?,?)",
                   ("Lecture de la semaine", "Lire un texte et préparer un résumé oral.", subject_id, class_id, user_ids["enseignant"], (today + timedelta(days=7)).isoformat(), year))

    db.execute("INSERT INTO absences(student_id,absence_date,reason,justified,school_year) VALUES(?,?,?,?,?)",
               (students[0][0], (today - timedelta(days=2)).isoformat(), "Rendez-vous médical", 1, year))
    for label, amount, days in (("Frais de scolarité - trimestre 1", 25000, 30), ("Fournitures scolaires", 8000, 45)):
        db.execute("INSERT INTO fee_schedules(label,amount,due_date,school_year) VALUES(?,?,?,?)",
                   (label, amount, (today + timedelta(days=days)).isoformat(), year))
    for index, (student_id, _class_id) in enumerate(students[:6], start=1):
        amount = 15000 if index % 2 else 8000
        db.execute("INSERT INTO payments(student_id,amount,paid_at,method,reference,school_year,created_by) VALUES(?,?,?,?,?,?,?)",
                   (student_id, amount, (today - timedelta(days=index)).isoformat(), "Mobile money" if index % 2 else "Espèces", f"DEMO-{index:03d}", year, accountant))
    db.execute("INSERT INTO messages(sender_id,recipient_id,subject,body,sent_at) VALUES(?,?,?,?,?)",
               (user_ids["enseignant"], user_ids["parent"], "Suivi scolaire d’Awa", "Awa participe bien en classe. Pensez à vérifier son devoir de lecture.", datetime.now().isoformat(timespec="minutes")))
    db.execute("INSERT INTO announcements(title,body,audience,created_by,created_at) VALUES(?,?,?,?,?)",
               ("Bienvenue pour la rentrée", "Les cours ont repris. Consultez l’emploi du temps et les informations de classe.", "all", admin_id, datetime.now().isoformat(timespec="minutes")))
    db.execute("INSERT INTO notifications(user_id,channel,message,status,created_at) VALUES(?,?,?,?,?)",
               (user_ids["parent"], "internal", "Un nouveau devoir de lecture est disponible.", "queued", datetime.now().isoformat(timespec="minutes")))
    db.execute("INSERT INTO pre_enrollments(first_name,last_name,birth_date,parent_name,parent_email,parent_phone,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
               ("Ndeye", "Camara", "2020-02-16", "Aissatou Camara", "aissatou@example.test", "+221 76 000 00 00", "pending", datetime.now().isoformat(timespec="minutes")))
    db.execute("INSERT INTO demo_seed(seed_key,created_at) VALUES(?,?)", ("school-demo-v2", datetime.now().isoformat(timespec="seconds")))


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
            if roles and user["role"] not in roles:
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username=? AND active=1", (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("Identifiants incorrects.", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required()
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def dashboard():
    db = get_db()
    if session.get("role") == "parent":
        parent_id=session["user_id"]
        totals={"students":db.execute("SELECT COUNT(*) FROM students WHERE active=1 AND parent_user_id=?",(parent_id,)).fetchone()[0],"classes":db.execute("SELECT COUNT(DISTINCT class_id) FROM students WHERE active=1 AND parent_user_id=?",(parent_id,)).fetchone()[0],"teachers":0}
        recent=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.parent_user_id=? ORDER BY s.id DESC LIMIT 5",(parent_id,)).fetchall()
    elif session.get("role")=="teacher":
        teacher_id=session["user_id"]
        totals={"students":db.execute("SELECT COUNT(*) FROM students WHERE active=1 AND class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)",(teacher_id,)).fetchone()[0],"classes":db.execute("SELECT COUNT(DISTINCT class_id) FROM teacher_assignments WHERE teacher_id=?",(teacher_id,)).fetchone()[0],"teachers":0}
        recent=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 AND s.class_id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?) ORDER BY s.id DESC LIMIT 5",(teacher_id,)).fetchall()
    elif session.get("role")=="student":
        totals={"students":db.execute("SELECT COUNT(*) FROM students WHERE student_user_id=?",(session["user_id"],)).fetchone()[0],"classes":db.execute("SELECT COUNT(DISTINCT class_id) FROM students WHERE student_user_id=?",(session["user_id"],)).fetchone()[0],"teachers":0}
        recent=db.execute("SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.student_user_id=?",(session["user_id"],)).fetchall()
    elif session.get("role")=="accountant":
        totals={"students":0,"classes":0,"teachers":0}
        recent=[]
    else:
        totals = {
            "students": db.execute("SELECT COUNT(*) FROM students WHERE active=1").fetchone()[0],
            "classes": db.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
            "teachers": db.execute("SELECT COUNT(*) FROM users WHERE role='teacher' AND active=1").fetchone()[0],
        }
        recent = db.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.active=1 ORDER BY s.id DESC LIMIT 5").fetchall()
    return render_template("dashboard.html", totals=totals, recent=recent)


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
@login_required("admin", "teacher")
def classes():
    db = get_db()
    if request.method == "POST":
        if session.get("role") != "admin":
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
    rows = db.execute("SELECT c.*, COUNT(s.id) AS student_count FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.active=1 WHERE (?='admin' OR c.id IN (SELECT class_id FROM teacher_assignments WHERE teacher_id=?)) GROUP BY c.id ORDER BY c.level,c.name",(session.get("role"),session["user_id"])).fetchall()
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
        if session.get("role") != "admin": abort(403)
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
@login_required("admin", "teacher", "parent", "student")
def timetable():
    db = get_db()
    if request.method == "POST":
        if session.get("role") != "admin": abort(403)
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
@login_required("admin", "teacher")
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
            return redirect(url_for("grades"))
        except (ValueError, KeyError):
            flash("Vérifie les informations de l'évaluation.", "danger")
    return render_template("evaluation_form.html", eval=ev, classes=classes, subjects=subjects)


@app.route("/evaluations/<int:eval_id>/delete", methods=["POST"])
@login_required("admin", "teacher")
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
@login_required("admin", "accountant", "parent")
def payments():
    db=get_db()
    if request.method == "POST":
        if session.get("role") == "parent": abort(403)
        try:
            student_id=int(request.form["student_id"]); amount=float(request.form["amount"])
            method=request.form["method"]
            student=db.execute("SELECT parent_name,parent_phone,parent_user_id,first_name,last_name,school_year FROM students WHERE id=? AND active=1",(student_id,)).fetchone()
            if not math.isfinite(amount) or amount <= 0 or method not in ("Espèces","Virement","Mobile money") or not student: raise ValueError
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
@login_required("admin", "teacher", "parent", "student")
def homework():
    db=get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin","teacher"): abort(403)
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
    elif session.get("role")=="admin":
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
@login_required("admin", "teacher")
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
            due_date = parse_iso_date(request.form["due_date"])
            if not title:
                raise ValueError("Le titre est obligatoire.")
            attachment = save_upload(request.files.get("attachment")) or work["attachment_path"]
            old_vals = {"title": work["title"], "due_date": work["due_date"]}
            db.execute("UPDATE homework SET title=?, description=?, subject_id=?, class_id=?, due_date=?, attachment_path=? WHERE id=?",
                       (title, request.form.get("description", "").strip(), subject_id, class_id, due_date.isoformat(), attachment, homework_id))
            audit("update", "homework", homework_id, old_vals, {"title": title, "due_date": due_date.isoformat()})
            db.commit()
            flash("Devoir mis à jour.", "success")
            return redirect(url_for("homework"))
        except (ValueError, KeyError):
            flash("Vérifie les informations du devoir.", "danger")
    return render_template("homework_form.html", homework=work, classes=classes, subjects=subjects)


@app.route("/homework/<int:homework_id>/delete", methods=["POST"])
@login_required("admin", "teacher")
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
@login_required("admin", "accountant")
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
@login_required("admin", "accountant")
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
@login_required("admin", "accountant")
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
        if role not in ("teacher","parent","accountant","secretary","student") or not username or not password or len(password)<8:
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
@login_required("admin", "teacher", "parent", "student")
def absences():
    db=get_db()
    if request.method == "POST":
        if session.get("role") in ("parent", "student"): abort(403)
        try:
            student_id=int(request.form["student_id"])
            student=db.execute("SELECT class_id,school_year FROM students WHERE id=? AND active=1",(student_id,)).fetchone()
            if not student: raise ValueError
            if session.get("role")=="teacher" and not db.execute("SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=? AND school_year=?",(session["user_id"],student["class_id"],student["school_year"])).fetchone(): abort(403)
            absence_date = parse_iso_date(request.form["absence_date"])
            if absence_date > date.today():
                raise ValueError("Une absence ne peut pas être dans le futur.")
            db.execute("INSERT INTO absences(student_id,absence_date,reason,school_year) VALUES(?,?,?,?)",(student_id,absence_date.isoformat(),request.form.get("reason","").strip(),student["school_year"]))
            db.commit(); flash("Absence enregistrée.","success")
        except (ValueError,KeyError): flash("Vérifie les informations de l'absence.","danger")
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
    referenced = db.execute("SELECT COUNT(*) FROM timetable WHERE room_id=?", (room_id,)).fetchone()[0]
    if referenced:
        db.execute("UPDATE rooms SET active=0 WHERE id=?", (room_id,))
        flash("Salle archivée pour préserver l'historique de l'emploi du temps.", "warning")
    else:
        db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
        flash("Salle supprimée.", "success")
    audit("delete", "room", room_id, {"name": room["name"]})
    db.commit()
    return redirect(url_for("rooms"))


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
