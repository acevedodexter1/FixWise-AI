"""Give an existing account admin access:  python make_admin.py you@example.com

Register the account on the website first. Use --remove to take admin access away again.
"""
import sys

from app import app
from extensions import db
from models import User


def main(argv):
    remove = "--remove" in argv
    emails = [a for a in argv[1:] if not a.startswith("--")]
    if len(emails) != 1:
        print("Usage: python make_admin.py <email> [--remove]")
        return 1
    with app.app_context():
        user = User.query.filter_by(email=emails[0].strip().lower()).first()
        if user is None:
            print(f"No account with the email {emails[0]}. Register it on the website first.")
            return 1
        user.role = "USER" if remove else "ADMIN"
        db.session.commit()
        print(f"{user.email} is now {user.role}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
