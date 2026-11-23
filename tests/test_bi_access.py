import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as school_app
from werkzeug.security import generate_password_hash


class BiAccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "test-bi-school.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")

        db = sqlite3.connect(school_app.DATABASE)
        db.execute("PRAGMA foreign_keys=ON")

        def add_user(username, role):
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role,full_name,school_id,active) VALUES(?,?,?,?,1,1)",
                (username, generate_password_hash("test-password"), role, username.title()),
            )
            return cursor.lastrowid

        self.admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.teacher_id = add_user("teacher_bi", "teacher")
        self.accountant_id = add_user("accountant_bi", "accountant")
        self.secretary_id = add_user("secretary_bi", "secretary")
        self.parent_id = add_user("parent_bi", "parent")
        self.student_id = add_user("student_bi", "student")
        db.commit()
        db.close()

    def tearDown(self):
        school_app.DATABASE = self.previous_database
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def client_for(self, user_id, role, username="user"):
        client = school_app.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["role"] = role
            session["username"] = username
            session["school_id"] = 1
        return client

    def test_parent_and_student_forbidden_from_bi(self):
        # Student cannot access /bi or /bi/dashboard/X
        student_client = self.client_for(self.student_id, "student", "student_bi")
        res = student_client.get("/bi")
        self.assertEqual(res.status_code, 403)
        res_d = student_client.get("/bi/dashboard/1")
        self.assertEqual(res_d.status_code, 403)

        # Parent cannot access /bi
        parent_client = self.client_for(self.parent_id, "parent", "parent_bi")
        res_p = parent_client.get("/bi")
        self.assertEqual(res_p.status_code, 403)

    def test_teacher_access_and_granularity(self):
        teacher_client = self.client_for(self.teacher_id, "teacher", "teacher_bi")
        res = teacher_client.get("/bi")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Teacher has tabs: 1 (Vue globale), 3 (Pédagogie), 4 (Absences), 8 (Salles), 9 (Early warning)
        self.assertIn("1. Vue Globale", html)
        self.assertIn("3. Pédagogie", html)
        self.assertIn("4. Absences", html)
        self.assertIn("9. Early Warning", html)

        # Teacher CANNOT view financial tab 2 or RH tab 5
        self.assertNotIn('id="tab2-btn"', html)
        self.assertNotIn('id="tab5-btn"', html)

        # Teacher cannot access restricted dashboard route directly
        res_forbidden = teacher_client.get("/bi/dashboard/2")
        self.assertEqual(res_forbidden.status_code, 403)
        res_allowed = teacher_client.get("/bi/dashboard/3")
        self.assertEqual(res_allowed.status_code, 302)

    def test_accountant_access_and_granularity(self):
        accountant_client = self.client_for(self.accountant_id, "accountant", "accountant_bi")
        res = accountant_client.get("/bi")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Accountant has finances (tab 2), inscriptions (tab 6), stratégie (tab 10)
        self.assertIn('id="tab2-btn"', html)
        self.assertIn('id="tab6-btn"', html)
        self.assertIn('id="tab10-btn"', html)

        # Accountant CANNOT access teacher RH tab 5 or Pédagogie tab 3
        self.assertNotIn('id="tab3-btn"', html)
        self.assertNotIn('id="tab5-btn"', html)

        res_forbidden = accountant_client.get("/bi/dashboard/3")
        self.assertEqual(res_forbidden.status_code, 403)
        res_allowed = accountant_client.get("/bi/dashboard/2")
        self.assertEqual(res_allowed.status_code, 302)

    def test_admin_has_full_access(self):
        admin_client = self.client_for(self.admin_id, "admin", "admin")
        res = admin_client.get("/bi")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        for i in range(1, 11):
            self.assertIn(f'id="tab{i}-btn"', html)
            res_d = admin_client.get(f"/bi/dashboard/{i}")
            self.assertEqual(res_d.status_code, 302)


if __name__ == "__main__":
    unittest.main()
