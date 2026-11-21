import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as school_app


class SchoolIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "isolation-school.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-isolation-secret")

        db = sqlite3.connect(school_app.DATABASE)
        db.row_factory = sqlite3.Row

        # Get school 1 (EXCELLENCE) and school 2 (HORIZON) users
        self.dir1 = db.execute("SELECT id, username, role, school_id FROM users WHERE username='directeur'").fetchone()
        self.dir2 = db.execute("SELECT id, username, role, school_id FROM users WHERE username='directeur_horizon'").fetchone()
        self.admin1 = db.execute("SELECT id, username, role, school_id FROM users WHERE username='admin'").fetchone()
        self.admin2 = db.execute("SELECT id, username, role, school_id FROM users WHERE username='admin_horizon'").fetchone()
        self.superadmin = db.execute("SELECT id, username, role, school_id FROM users WHERE username='superadmin'").fetchone()

        # Students
        self.student_a = db.execute("SELECT id, first_name, last_name, school_id FROM students WHERE school_id=1 LIMIT 1").fetchone()
        self.student_b = db.execute("SELECT id, first_name, last_name, school_id FROM students WHERE school_id=2 LIMIT 1").fetchone()

        # Classes
        self.class_a = db.execute("SELECT id, name, school_id FROM classes WHERE school_id=1 LIMIT 1").fetchone()
        self.class_b = db.execute("SELECT id, name, school_id FROM classes WHERE school_id=2 LIMIT 1").fetchone()

        # Payments
        self.payment_a = db.execute("SELECT id, student_id, school_id FROM payments WHERE school_id=1 LIMIT 1").fetchone()
        self.payment_b = db.execute("SELECT id, student_id, school_id FROM payments WHERE school_id=2 LIMIT 1").fetchone()

        db.close()

    def tearDown(self):
        school_app.DATABASE = self.previous_database
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def client_for(self, user_dict):
        client = school_app.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user_dict["id"]
            sess["username"] = user_dict["username"]
            sess["role"] = user_dict["role"]
            sess["school_id"] = user_dict["school_id"]
        return client

    def test_bidirectional_student_list_isolation(self):
        # Director 1 must only see School A students, never School B
        c1 = self.client_for(self.dir1)
        resp1 = c1.get("/students")
        self.assertEqual(resp1.status_code, 200)
        content1 = resp1.data.decode("utf-8")
        self.assertIn("A-Élève", content1)
        self.assertNotIn("B-Élève", content1)

        # Director 2 must only see School B students, never School A
        c2 = self.client_for(self.dir2)
        resp2 = c2.get("/students")
        self.assertEqual(resp2.status_code, 200)
        content2 = resp2.data.decode("utf-8")
        self.assertIn("B-Élève", content2)
        self.assertNotIn("A-Élève", content2)

    def test_leak_zone_direct_student_id_returns_404(self):
        # Director 1 accessing School B student directly via ID must get 404
        c1 = self.client_for(self.dir1)
        resp = c1.get(f"/students/{self.student_b['id']}")
        self.assertEqual(resp.status_code, 404)

        # Director 2 accessing School A student directly via ID must get 404
        c2 = self.client_for(self.dir2)
        resp = c2.get(f"/students/{self.student_a['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_leak_zone_direct_class_id_returns_404(self):
        c1 = self.client_for(self.dir1)
        resp = c1.get(f"/classes/{self.class_b['id']}/edit")
        self.assertEqual(resp.status_code, 404)

        c2 = self.client_for(self.dir2)
        resp = c2.get(f"/classes/{self.class_a['id']}/edit")
        self.assertEqual(resp.status_code, 404)

    def test_leak_zone_direct_payment_receipt_returns_404(self):
        c1 = self.client_for(self.dir1)
        resp = c1.get(f"/payments/{self.payment_b['id']}/receipt.pdf")
        self.assertEqual(resp.status_code, 404)

        c2 = self.client_for(self.dir2)
        resp = c2.get(f"/payments/{self.payment_a['id']}/receipt.pdf")
        self.assertEqual(resp.status_code, 404)

    def test_school_switch_permission(self):
        # Director 1 trying to switch to School 2 must be rejected with 403
        c1 = self.client_for(self.dir1)
        resp = c1.get("/schools/switch/2")
        self.assertEqual(resp.status_code, 403)

        # Superadmin can switch to School 2 (returns 302 redirect)
        c_super = self.client_for(self.superadmin)
        resp = c_super.get("/schools/switch/2")
        self.assertEqual(resp.status_code, 302)


if __name__ == "__main__":
    unittest.main()
