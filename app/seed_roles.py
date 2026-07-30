"""Seed script to ensure system roles exist in the role table.

Run with: python -m app.seed_roles
"""

from app.core.database import SessionLocal
from app.models.role import Role


def seed_roles():
    db = SessionLocal()
    try:
        roles = {"user": 1, "admin": 2}
        for type_name, role_id in roles.items():
            existing = db.query(Role).filter(Role.id == role_id).first()
            if not existing:
                db.add(Role(id=role_id, type=type_name))
                print(f"Created role: id={role_id}, type={type_name}")
            else:
                print(f"Role already exists: id={role_id}, type={existing.type}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_roles()
