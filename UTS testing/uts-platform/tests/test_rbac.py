"""Integration tests for User Management and server-side RBAC."""

from __future__ import annotations

import unittest

from webapp import create_app
from webapp.models import AccessRole, AuditLog, User, db


class RBACTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "SECRET_KEY": "test-secret",
            }
        )
        self.client = self.app.test_client()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def login(self, username: str = "admin", password: str = "admin123"):
        self.client.get("/login")
        return self.client.post(
            "/login",
            data={
                "username": username,
                "password": password,
                "_csrf_token": self.csrf(),
            },
            follow_redirects=False,
        )

    def logout(self):
        return self.client.post(
            "/logout",
            data={"_csrf_token": self.csrf()},
            follow_redirects=False,
        )

    def test_admin_seeded_with_unrestricted_role(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").one()
            self.assertEqual(admin.access_role.name, "Administrator")
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 200)

    def test_login_does_not_accept_client_selected_role(self):
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "username": "admin",
                "password": "admin123",
                "role": "Viewer",
                "_csrf_token": self.csrf(),
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").one()
            self.assertEqual(admin.access_role.name, "Administrator")

    def test_viewer_cannot_create_project_by_direct_post(self):
        self.login()
        with self.app.app_context():
            viewer = AccessRole.query.filter_by(name="Viewer").one()
        response = self.client.post(
            "/admin/users",
            data={
                "employee_name": "Read Only User",
                "username": "viewer1",
                "password": "Strong!Pass123",
                "role_id": viewer.id,
                "is_active": "on",
                "_csrf_token": self.csrf(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.logout()
        self.login("viewer1", "Strong!Pass123")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        denied = self.client.post(
            "/projects",
            data={
                "name": "Forbidden",
                "application_url": "https://example.com",
                "_csrf_token": self.csrf(),
            },
        )
        self.assertEqual(denied.status_code, 403)

    def test_deactivated_user_cannot_login(self):
        self.login()
        with self.app.app_context():
            viewer = AccessRole.query.filter_by(name="Viewer").one()
        self.client.post(
            "/admin/users",
            data={
                "employee_name": "Inactive User",
                "username": "inactive1",
                "password": "Strong!Pass123",
                "role_id": viewer.id,
                "_csrf_token": self.csrf(),
            },
        )
        self.logout()
        response = self.login("inactive1", "Strong!Pass123")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Your account is inactive", response.data)

    def test_csrf_blocks_mutating_request(self):
        self.login()
        response = self.client.post(
            "/projects",
            data={"name": "No Token", "application_url": "https://example.com"},
        )
        self.assertEqual(response.status_code, 400)

    def test_authentication_events_are_audited(self):
        self.login()
        self.logout()
        with self.app.app_context():
            actions = {entry.action for entry in AuditLog.query.all()}
            self.assertIn("LOGIN", actions)
            self.assertIn("LOGOUT", actions)


if __name__ == "__main__":
    unittest.main()
