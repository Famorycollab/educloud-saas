import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as school_app


class StudentFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "test-school-student.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")

        db = sqlite3.connect(school_app.DATABASE)
        self.admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.parent_id = db.execute("SELECT id FROM users WHERE username='parent'").fetchone()[0]
        self.student = db.execute("SELECT id, first_name, last_name FROM students WHERE parent_user_id=?", (self.parent_id,)).fetchone()
        self.student_id = self.student[0]
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

    def test_student_detail_access(self):
        # Admin can view student detail
        self.login("admin", "admin", self.admin_id)
        resp = self.client.get(f"/students/{self.student_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.student[1], resp.get_data(as_text=True))

        # Linked parent can view their child's detail
        self.login("parent", "parent", self.parent_id)
        resp = self.client.get(f"/students/{self.student_id}")
        self.assertEqual(resp.status_code, 200)

    def test_student_edit_with_medical_notes(self):
        self.login("admin", "admin", self.admin_id)
        resp = self.client.post(
            f"/students/{self.student_id}/edit",
            data={
                "csrf_token": "valid-token",
                "first_name": "Awa",
                "last_name": "Ndiaye",
                "birth_date": "2019-04-12",
                "school_year": "2026-2027",
                "parent_name": "Fatou Ndiaye",
                "medical_notes": "Allergie aux arachides.",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        notes = db.execute("SELECT medical_notes FROM students WHERE id=?", (self.student_id,)).fetchone()[0]
        db.close()
        self.assertEqual(notes, "Allergie aux arachides.")


if __name__ == "__main__":
    unittest.main()

