import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as school_app
from werkzeug.security import check_password_hash, generate_password_hash


class CrudOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "test-school-crud.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")

        db = sqlite3.connect(school_app.DATABASE)
        db.execute("PRAGMA foreign_keys=ON")

        self.admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.teacher_id = db.execute("SELECT id FROM users WHERE username='enseignant'").fetchone()[0]
        self.parent_id = db.execute("SELECT id FROM users WHERE username='parent'").fetchone()[0]
        self.student_id = db.execute("SELECT id FROM students WHERE parent_user_id=?", (self.parent_id,)).fetchone()[0]
        self.class_id = db.execute("SELECT id FROM classes WHERE name='CP-A'").fetchone()[0]
        self.subject_id = db.execute("SELECT id FROM subjects WHERE level='CP' LIMIT 1").fetchone()[0]
        db.close()

        self.client = school_app.app.test_client()

    def tearDown(self):
        school_app.DATABASE = self.previous_database
        self.temp_dir.cleanup()

    def login(self, username, role, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username
            sess["role"] = role
            sess["csrf_token"] = "valid-token"

    def test_class_edit(self):
        self.login("admin", "admin", self.admin_id)
        # GET edit form
        resp = self.client.get(f"/classes/{self.class_id}/edit")
        self.assertEqual(resp.status_code, 200)

        # POST update
        resp = self.client.post(
            f"/classes/{self.class_id}/edit",
            data={
                "csrf_token": "valid-token",
                "name": "CP-Modifie",
                "level": "CP",
                "section": "B",
                "capacity": "28",
                "school_year": "2026-2027",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        cls = db.execute("SELECT name, capacity FROM classes WHERE id=?", (self.class_id,)).fetchone()
        db.close()
        self.assertEqual(cls[0], "CP-Modifie")
        self.assertEqual(cls[1], 28)

    def test_subject_edit(self):
        self.login("admin", "admin", self.admin_id)
        resp = self.client.get(f"/subjects/{self.subject_id}/edit")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            f"/subjects/{self.subject_id}/edit",
            data={
                "csrf_token": "valid-token",
                "name": "Français Avancé",
                "level": "CP",
                "coefficient": "3.0",
                "school_year": "2026-2027",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        sub = db.execute("SELECT name, coefficient FROM subjects WHERE id=?", (self.subject_id,)).fetchone()
        db.close()
        self.assertEqual(sub[0], "Français Avancé")
        self.assertEqual(sub[1], 3.0)

    def test_room_crud(self):
        self.login("admin", "admin", self.admin_id)
        # Create a new standalone room
        resp = self.client.post(
            "/rooms",
            data={
                "csrf_token": "valid-token",
                "name": "Salle Info",
                "capacity": "20",
                "availability": "Tous les jours",
                "school_year": "2026-2027",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        room_id = db.execute("SELECT id FROM rooms WHERE name='Salle Info'").fetchone()[0]
        db.close()

        # Edit room
        resp = self.client.post(
            f"/rooms/{room_id}/edit",
            data={
                "csrf_token": "valid-token",
                "name": "Labo Info",
                "capacity": "25",
                "availability": "Matin",
                "school_year": "2026-2027",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        room = db.execute("SELECT name, capacity FROM rooms WHERE id=?", (room_id,)).fetchone()
        self.assertEqual(room[0], "Labo Info")
        self.assertEqual(room[1], 25)

        # Delete room
        self.client.post(f"/rooms/{room_id}/delete", data={"csrf_token": "valid-token"}, follow_redirects=True)
        remaining = db.execute("SELECT 1 FROM rooms WHERE id=?", (room_id,)).fetchone()
        db.close()
        self.assertIsNone(remaining)

    def test_fee_schedule_crud(self):
        self.login("admin", "admin", self.admin_id)
        # Create fee
        self.client.post(
            "/fee-schedules",
            data={"csrf_token": "valid-token", "label": "Sortie musée", "amount": "1500", "school_year": "2026-2027"},
            follow_redirects=True,
        )
        db = sqlite3.connect(school_app.DATABASE)
        fee_id = db.execute("SELECT id FROM fee_schedules WHERE label='Sortie musée'").fetchone()[0]
        db.close()

        # Edit fee
        self.client.post(
            f"/fee-schedules/{fee_id}/edit",
            data={"csrf_token": "valid-token", "label": "Sortie musée modifiée", "amount": "2000", "school_year": "2026-2027"},
            follow_redirects=True,
        )
        db = sqlite3.connect(school_app.DATABASE)
        fee = db.execute("SELECT label, amount FROM fee_schedules WHERE id=?", (fee_id,)).fetchone()
        self.assertEqual(fee[0], "Sortie musée modifiée")
        self.assertEqual(fee[1], 2000.0)

        # Delete fee
        self.client.post(f"/fee-schedules/{fee_id}/delete", data={"csrf_token": "valid-token"}, follow_redirects=True)
        remaining = db.execute("SELECT 1 FROM fee_schedules WHERE id=?", (fee_id,)).fetchone()
        db.close()
        self.assertIsNone(remaining)

    def test_user_profile_and_edit(self):
        self.login("admin", "admin", self.admin_id)
        # Admin edits teacher profile
        resp = self.client.post(
            f"/users/{self.teacher_id}/edit",
            data={
                "csrf_token": "valid-token",
                "full_name": "Mamadou Ba Modifié",
                "email": "m.ba.updated@example.test",
                "role": "teacher",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        user = db.execute("SELECT full_name, email FROM users WHERE id=?", (self.teacher_id,)).fetchone()
        self.assertEqual(user[0], "Mamadou Ba Modifié")
        self.assertEqual(user[1], "m.ba.updated@example.test")

        # Now login as parent and update own profile info
        self.login("parent", "parent", self.parent_id)
        resp = self.client.get("/profile")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            "/profile/info",
            data={"csrf_token": "valid-token", "full_name": "Fatou Ndiaye Nouveau", "email": "fatou.new@example.test"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        user = db.execute("SELECT full_name, email FROM users WHERE id=?", (self.parent_id,)).fetchone()
        self.assertEqual(user[0], "Fatou Ndiaye Nouveau")
        self.assertEqual(user[1], "fatou.new@example.test")

        # Parent updates own password
        resp = self.client.post(
            "/profile/password",
            data={
                "csrf_token": "valid-token",
                "current_password": "parent123",
                "new_password": "nouveaumotdepasse123",
                "confirm_password": "nouveaumotdepasse123",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        pw_hash = db.execute("SELECT password_hash FROM users WHERE id=?", (self.parent_id,)).fetchone()[0]
        db.close()
        self.assertTrue(check_password_hash(pw_hash, "nouveaumotdepasse123"))


if __name__ == "__main__":
    unittest.main()

