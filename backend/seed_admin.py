#!/usr/bin/env python3
"""
Create the initial admin user.

Usage:
    python seed_admin.py <username> <password> [cohort_id]

Example:
    python seed_admin.py admin changeme admin
"""
import sys
import uuid
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from database import get_db, init_db, is_unique_constraint_error


def create_admin(username, password, cohort_id='admin'):
    init_db()
    user_id = str(uuid.uuid4())
    password_hash = generate_password_hash(password)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_db() as conn:
            conn.execute(
                '''INSERT INTO users
                   (user_id, username, password_hash, cohort_id, is_admin, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)''',
                (user_id, username, password_hash, cohort_id, created_at)
            )
        print(f'Admin user created successfully.')
        print(f'  Username : {username}')
        print(f'  User ID  : {user_id}')
        print(f'  Cohort   : {cohort_id}')
    except Exception as e:
        if is_unique_constraint_error(e):
            print(f"Error: Username '{username}' already exists.")
            sys.exit(1)
        raise


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    _username = sys.argv[1]
    _password = sys.argv[2]
    _cohort = sys.argv[3] if len(sys.argv) > 3 else 'admin'
    create_admin(_username, _password, _cohort)
