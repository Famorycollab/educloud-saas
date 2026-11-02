import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

import app as school_app
from werkzeug.security import generate_password_hash


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "test-school.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")

        db = sqlite3.connect(school_app.DATABASE)
        db.execute("PRAGMA foreign_keys=ON")

        def add_user(username, role):
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role,full_name) VALUES(?,?,?,?)",
                (username, generate_password_hash("test-password"), role, username.title()),
            )
            return cursor.lastrowid

        self.admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.teacher_id = add_user("teacher_test", "teacher")
        self.parent_id = add_user("parent_test", "parent")
        self.other_parent_id = add_user("other_parent", "parent")
        self.student_user_id = add_user("student_test", "student")

        self.class_a = db.execute(
            "INSERT INTO classes(name,level,capacity,school_year) VALUES('CP-A','CP',1,'2026-2027')"
        ).lastrowid
        self.class_b = db.execute(
            "INSERT INTO classes(name,level,capacity,school_year) VALUES('CE1-B','CE1',10,'2026-2027')"
        ).lastrowid
        self.subject_id = db.execute(
            "INSERT INTO subjects(name,level,school_year) VALUES('Français','CP','2026-2027')"
        ).lastrowid
        db.execute(
            "INSERT INTO teacher_assignments(teacher_id,subject_id,class_id,school_year) VALUES(?,?,?,'2026-2027')",
            (self.teacher_id, self.subject_id, self.class_a),
        )
        self.child_id = db.execute(
            "INSERT INTO students(first_name,last_name,parent_user_id,student_user_id,class_id,school_year) VALUES('Enfant','Parent',?,?,?,'2026-2027')",
            (self.parent_id, self.student_user_id, self.class_a),
        ).lastrowid
        self.other_child_id = db.execute(
            "INSERT INTO students(first_name,last_name,parent_user_id,class_id,school_year) VALUES('Autre','Famille',?,?, '2026-2027')",
            (self.other_parent_id, self.class_b),
        ).lastrowid
        self.evaluation_b = db.execute(
            "INSERT INTO evaluations(title,subject_id,class_id,evaluation_date,max_score,school_year) VALUES('Évaluation CE1',?,?, '2026-10-10',20,'2026-2027')",
            (self.subject_id, self.class_b),
        ).lastrowid
        db.commit()
        db.close()

    def tearDown(self):
        school_app.DATABASE = self.previous_database
        self.temp_dir.cleanup()

    def client_for(self, user_id, role):
        client = school_app.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["role"] = role
            session["username"] = "test"
        return client

    def csrf_for(self, client, page):
        response = client.get(page)
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as session:
            return session["csrf_token"]

    def test_demo_data_covers_modules_and_initialization_is_idempotent(self):
        db = sqlite3.connect(school_app.DATABASE)
        tables = (
            "classes", "students", "subjects", "rooms", "teacher_assignments",
            "timetable", "evaluations", "grades", "absences", "fee_schedules",
            "payments", "homework", "messages", "announcements", "notifications",
            "pre_enrollments",
        )
        before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        demo_accounts = db.execute(
            "SELECT COUNT(*) FROM users WHERE username IN ('enseignant','parent','eleve','secretaire')"
        ).fetchone()[0]
        self.assertEqual(demo_accounts, 4)
        self.assertTrue(all(count > 0 for count in before.values()), before)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM students WHERE first_name IN ('Awa','Ibrahima','Fatou','Cheikh','Aminata','Marième','Moussa')").fetchone()[0], 7)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM payments WHERE reference LIKE 'DEMO-%'").fetchone()[0], 6)
        self.assertGreaterEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='parent'").fetchone()[0], 3)
        year_tables = (
            "classes", "students", "subjects", "rooms", "teacher_assignments",
            "timetable", "evaluations", "absences", "fee_schedules", "payments", "homework",
        )
        for table in year_tables:
            years = {row[0] for row in db.execute(f"SELECT DISTINCT school_year FROM {table}")}
            self.assertEqual(years, {"2026-2027"}, table)
        homework_due = db.execute("SELECT MIN(due_date) FROM homework").fetchone()[0]
        absence_date = db.execute("SELECT MAX(absence_date) FROM absences").fetchone()[0]
        self.assertGreater(date.fromisoformat(homework_due), date.today())
        self.assertLessEqual(date.fromisoformat(absence_date), date.today())
        db.close()

        school_app.init_db()
        db = sqlite3.connect(school_app.DATABASE)
        after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        db.close()
        self.assertEqual(before, after)

    def test_date_constraints_reject_invalid_and_future_birth_dates(self):
        self.assertTrue(school_app.is_valid_birth_date("2020-02-29"))
        self.assertTrue(school_app.is_valid_birth_date(""))
        self.assertFalse(school_app.is_valid_birth_date("2021-02-29"))
        self.assertFalse(school_app.is_valid_birth_date("not-a-date"))
        self.assertFalse(school_app.is_valid_birth_date("2999-01-01"))

        client = self.client_for(self.admin_id, "admin")
        csrf = self.csrf_for(client, "/students/new")
        response = client.post("/students/new", data={
            "csrf_token": csrf,
            "first_name": "Date",
            "last_name": "Invalide",
            "birth_date": "not-a-date",
        })
        self.assertEqual(response.status_code, 200)
        db = sqlite3.connect(school_app.DATABASE)
        count = db.execute(
            "SELECT COUNT(*) FROM students WHERE first_name='Date' AND last_name='Invalide'"
        ).fetchone()[0]
        db.close()
        self.assertEqual(count, 0)

    def test_parent_only_sees_linked_children(self):
        response = self.client_for(self.parent_id, "parent").get("/students")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enfant Parent", response.data)
        self.assertNotIn(b"Autre Famille", response.data)

    def test_role_is_loaded_from_database_not_session(self):
        client = self.client_for(self.parent_id, "admin")
        response = client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_grade_an_unassigned_class(self):
        client = self.client_for(self.teacher_id, "teacher")
        csrf = self.csrf_for(client, "/grades")
        response = client.post("/grades", data={
            "csrf_token": csrf,
            "evaluation_id": self.evaluation_b,
            "student_id": self.other_child_id,
            "score": "15",
        })
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_open_another_students_dossier(self):
        client = self.client_for(self.parent_id, "parent")
        response = client.get(f"/students/{self.other_child_id}/edit")
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_download_another_students_bulletin(self):
        client = self.client_for(self.parent_id, "parent")
        response = client.get(f"/reports/bulletin/{self.other_child_id}.pdf")
        self.assertEqual(response.status_code, 403)

    def test_disabled_account_session_is_revoked(self):
        db = sqlite3.connect(school_app.DATABASE)
        db.execute("UPDATE users SET active=0 WHERE id=?", (self.parent_id,))
        db.commit()
        db.close()
        response = self.client_for(self.parent_id, "parent").get("/students")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_timetable_rejects_overlapping_class_and_teacher(self):
        db = sqlite3.connect(school_app.DATABASE)
        db.execute(
            "INSERT INTO timetable(class_id,teacher_id,subject_id,weekday,start_time,end_time,school_year) VALUES(?,?,?,1,'08:00','09:00','2026-2027')",
            (self.class_a, self.teacher_id, self.subject_id),
        )
        db.commit()
        db.close()
        client = self.client_for(self.admin_id, "admin")
        csrf = self.csrf_for(client, "/timetable")
        response = client.post("/timetable", data={
            "csrf_token": csrf,
            "class_id": str(self.class_a),
            "teacher_id": str(self.teacher_id),
            "subject_id": str(self.subject_id),
            "weekday": "1",
            "start_time": "08:30",
            "end_time": "09:30",
            "school_year": "2026-2027",
        })
        self.assertEqual(response.status_code, 200)
        db = sqlite3.connect(school_app.DATABASE)
        count = db.execute("SELECT COUNT(*) FROM timetable WHERE class_id=?", (self.class_a,)).fetchone()[0]
        db.close()
        self.assertEqual(count, 1)

    def test_administrator_pages_render(self):
        client = self.client_for(self.admin_id, "admin")
        pages = [
            "/", "/students", "/classes", "/subjects", "/timetable", "/grades",
            "/payments", "/fee-schedules", "/homework", "/messages", "/announcements",
            "/notifications", "/rooms", "/users", "/assignments", "/pre-enrollments", "/absences",
        ]
        for page in pages:
            with self.subTest(page=page):
                self.assertEqual(client.get(page).status_code, 200)

    def test_post_without_csrf_token_is_rejected(self):
        client = self.client_for(self.admin_id, "admin")
        response = client.post("/students/new", data={"first_name": "Intrus", "last_name": "Test"})
        self.assertEqual(response.status_code, 400)

    def test_admin_can_disable_an_account_but_not_the_last_admin(self):
        admin_client = self.client_for(self.admin_id, "admin")
        csrf = self.csrf_for(admin_client, "/users")
        response = admin_client.post(f"/users/{self.parent_id}/toggle", data={"csrf_token": csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client_for(self.parent_id, "parent").get("/students").status_code, 302)

        response = admin_client.post(f"/users/{self.admin_id}/toggle", data={"csrf_token": csrf})
        self.assertEqual(response.status_code, 302)
        db = sqlite3.connect(school_app.DATABASE)
        active_admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        db.close()
        self.assertEqual(active_admins, 1)

    def test_class_capacity_is_enforced(self):
        client = self.client_for(self.admin_id, "admin")
        csrf = self.csrf_for(client, "/students/new")
        response = client.post("/students/new", data={
            "csrf_token": csrf,
            "first_name": "Deuxième",
            "last_name": "Élève",
            "class_id": str(self.class_a),
            "school_year": "2026-2027",
        })
        self.assertEqual(response.status_code, 200)
        db = sqlite3.connect(school_app.DATABASE)
        count = db.execute("SELECT COUNT(*) FROM students WHERE class_id=?", (self.class_a,)).fetchone()[0]
        db.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
