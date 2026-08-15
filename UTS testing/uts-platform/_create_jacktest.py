
import os
os.chdir(r"C:\Software_Automation\UTS-Test-Automation-Suite 3\UTS-Test-Automation-Suite")
from werkzeug.security import generate_password_hash
from webapp import create_app
from webapp.models import AccessRole, User, db
from webapp.rbac import record_audit, sync_builtin_role_permissions

app = create_app()
with app.app_context():
    sync_builtin_role_permissions()
    role = AccessRole.query.filter(db.func.lower(AccessRole.name) == "testuser").first()
    if not role:
        role = AccessRole.query.filter(AccessRole.name.ilike("%test%")).first()
    print("ROLE", role.id if role else None, role.name if role else None)
    existing = User.query.filter(db.func.lower(User.username) == "jacktest").first()
    password = "C!sco@123"
    if existing:
        existing.password_hash = generate_password_hash(password)
        existing.is_active = True
        existing.is_deleted = False
        existing.employee_name = existing.employee_name or "Jack Test"
        if role:
            existing.role_id = role.id
        db.session.commit()
        print("UPDATED", existing.id, existing.username, "role", existing.role_id)
    else:
        user = User(
            username="JackTest",
            employee_name="Jack Test",
            password_hash=generate_password_hash(password),
            role_id=role.id if role else None,
            is_active=True,
            is_deleted=False,
        )
        db.session.add(user)
        db.session.flush()
        record_audit(
            "USER_CREATED",
            "user_management",
            target=user,
            remarks="Created JackTest for user guide",
            commit=False,
        )
        db.session.commit()
        print("CREATED", user.id, user.username, "role", user.role_id)
