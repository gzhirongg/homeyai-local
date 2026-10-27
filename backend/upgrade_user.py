import sys
import os

# Ensure backend directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import SessionLocal, User, UserRole

def upgrade_user(email: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"User {email} not found.")
            return

        user.role = UserRole.PREMIUM
        db.commit()
        print(f"User {email} successfully upgraded to PREMIUM.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python upgrade_user.py <email>")
    else:
        upgrade_user(sys.argv[1])
