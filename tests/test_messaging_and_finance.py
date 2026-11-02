import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as school_app


class MessagingAndFinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database = school_app.DATABASE
        school_app.DATABASE = Path(self.temp_dir.name) / "test-school-mf.db"
        school_app.init_db()
        school_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")

        db = sqlite3.connect(school_app.DATABASE)
        self.admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.teacher_id = db.execute("SELECT id FROM users WHERE username='enseignant'").fetchone()[0]
        self.parent_id = db.execute("SELECT id FROM users WHERE username='parent'").fetchone()[0]
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

    def test_message_draft_and_send(self):
        # Teacher creates a draft to parent
        self.login("enseignant", "teacher", self.teacher_id)
        resp = self.client.post(
            "/messages",
            data={
                "csrf_token": "valid-token",
                "recipient_id": str(self.parent_id),
                "subject": "Brouillon test",
                "body": "Corps du brouillon",
                "action": "draft",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        draft = db.execute("SELECT id, is_draft FROM messages WHERE subject='Brouillon test'").fetchone()
        self.assertIsNotNone(draft)
        self.assertEqual(draft[1], 1)
        draft_id = draft[0]
        db.close()

        # Parent should not see the draft
        self.login("parent", "parent", self.parent_id)
        resp = self.client.get("/messages")
        self.assertNotIn("Brouillon test", resp.get_data(as_text=True))

        # Teacher sends the draft
        self.login("enseignant", "teacher", self.teacher_id)
        resp = self.client.post(f"/messages/{draft_id}/send-draft", data={"csrf_token": "valid-token"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        msg = db.execute("SELECT is_draft FROM messages WHERE id=?", (draft_id,)).fetchone()
        self.assertEqual(msg[0], 0)
        db.close()

        # Parent now sees it
        self.login("parent", "parent", self.parent_id)
        resp = self.client.get("/messages")
        self.assertIn("Brouillon test", resp.get_data(as_text=True))

        # Parent hides the message
        self.client.post(f"/messages/{draft_id}/hide", data={"csrf_token": "valid-token"}, follow_redirects=True)
        resp = self.client.get("/messages")
        self.assertNotIn("Brouillon test", resp.get_data(as_text=True))

        # But teacher still has it in sent messages (immutability)
        self.login("enseignant", "teacher", self.teacher_id)
        resp = self.client.get("/messages")
        self.assertIn("Brouillon test", resp.get_data(as_text=True))

    def test_payment_export_and_reminders(self):
        self.login("admin", "admin", self.admin_id)
        # Test CSV export
        resp = self.client.get("/payments/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])

        # Test automated reminders
        resp = self.client.post("/payments/send-reminders", data={"csrf_token": "valid-token"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        db = sqlite3.connect(school_app.DATABASE)
        notifs = db.execute("SELECT COUNT(*) FROM notifications WHERE message LIKE 'Rappel : Solde%'").fetchone()[0]
        db.close()
        self.assertGreater(notifs, 0)


if __name__ == "__main__":
    unittest.main()

