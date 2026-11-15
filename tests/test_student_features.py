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
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

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

    def test_exams_and_calendar_access(self):
        # Admin can view exams and calendar
        self.login("admin", "admin", self.admin_id)
        resp_exams = self.client.get("/exams")
        self.assertEqual(resp_exams.status_code, 200)
        self.assertIn("Contrôles", resp_exams.get_data(as_text=True))

        resp_cal = self.client.get("/calendar")
        self.assertEqual(resp_cal.status_code, 200)
        self.assertIn("Calendrier", resp_cal.get_data(as_text=True))

        # Parent can view exams and calendar
        self.login("parent", "parent", self.parent_id)
        resp_p_exams = self.client.get("/exams")
        self.assertEqual(resp_p_exams.status_code, 200)

        resp_p_cal = self.client.get("/calendar")
        self.assertEqual(resp_p_cal.status_code, 200)

    def test_plan_exam_and_school_event(self):
        self.login("admin", "admin", self.admin_id)
        db = sqlite3.connect(school_app.DATABASE)
        cid = db.execute("SELECT id FROM classes LIMIT 1").fetchone()[0]
        sid = db.execute("SELECT id FROM subjects WHERE level=(SELECT level FROM classes WHERE id=?)", (cid,)).fetchone()[0]
        db.close()

        # Admin plans an exam
        resp = self.client.post("/exams", data={
            "csrf_token": "valid-token",
            "title": "Devoir Surveillé Algèbre",
            "eval_type": "Devoir Surveillé",
            "subject_id": sid,
            "class_id": cid,
            "max_score": "20",
            "evaluation_date": "2026-12-10",
            "start_time": "08:30",
            "end_time": "10:30",
            "instructions": "Calculatrice interdite.",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Admin adds school event
        resp_ev = self.client.post("/calendar", data={
            "csrf_token": "valid-token",
            "title": "Conseil Pédagogique",
            "event_type": "meeting",
            "audience": "teachers",
            "start_date": "2026-12-15",
            "end_date": "2026-12-15",
            "start_time": "14:00",
            "end_time": "16:00",
            "description": "Coordination du trimestre.",
        }, follow_redirects=True)
        self.assertEqual(resp_ev.status_code, 200)

    def test_date_and_logical_constraints(self):
        self.login("admin", "admin", self.admin_id)
        db = sqlite3.connect(school_app.DATABASE)
        cid = db.execute("SELECT id FROM classes LIMIT 1").fetchone()[0]
        sid = db.execute("SELECT id FROM subjects WHERE level=(SELECT level FROM classes WHERE id=?)", (cid,)).fetchone()[0]
        rid = db.execute("SELECT id FROM rooms LIMIT 1").fetchone()[0]
        db.close()

        # 1. Exam with end_time <= start_time must be rejected
        resp = self.client.post("/exams", data={
            "csrf_token": "valid-token",
            "title": "Contrôle Invalide",
            "eval_type": "Devoir Surveillé",
            "subject_id": sid,
            "class_id": cid,
            "max_score": "20",
            "evaluation_date": "2026-12-11",
            "start_time": "11:00",
            "end_time": "09:00",
        }, follow_redirects=True)
        self.assertIn("postérieure à l&#39;heure de début", resp.get_data(as_text=True))

        # 2. Calendar event with end_date < start_date must be rejected
        resp_cal = self.client.post("/calendar", data={
            "csrf_token": "valid-token",
            "title": "Événement Date Invalide",
            "event_type": "event",
            "audience": "all",
            "start_date": "2026-12-20",
            "end_date": "2026-12-10",
        }, follow_redirects=True)
        self.assertIn("La date de fin ne peut pas être antérieure", resp_cal.get_data(as_text=True))

        # 3. Absence in the future must be rejected
        resp_abs = self.client.post("/absences", data={
            "csrf_token": "valid-token",
            "student_id": self.student_id,
            "absence_date": "2029-01-01",
            "reason": "Absence future impossible",
        }, follow_redirects=True)
        self.assertIn("dans le futur", resp_abs.get_data(as_text=True))

        # 4. Duplicate absence for same student on same date must be rejected
        resp_abs_ok = self.client.post("/absences", data={
            "csrf_token": "valid-token",
            "student_id": self.student_id,
            "absence_date": "2026-10-15",
            "reason": "Maladie",
        }, follow_redirects=True)
        self.assertIn("Absence enregistrée", resp_abs_ok.get_data(as_text=True))

        resp_abs_dup = self.client.post("/absences", data={
            "csrf_token": "valid-token",
            "student_id": self.student_id,
            "absence_date": "2026-10-15",
            "reason": "Doublon",
        }, follow_redirects=True)
        self.assertIn("déjà été enregistrée", resp_abs_dup.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

