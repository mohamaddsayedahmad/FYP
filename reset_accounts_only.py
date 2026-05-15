"""Reset ONLY the accounts table (keeps users/courses/attendance).

Use this if your accounts table contains corrupted salt/hash values
and you want to recreate default accounts.

Default accounts recreated by database.init_db():
  admin   / admin123
  teacher / teacher123

Run:
  python reset_accounts_only.py
"""

import sqlite3

DB_PATH = "attendance.db"

def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("DROP TABLE IF EXISTS accounts;")
        conn.commit()
        print("✓ Accounts table dropped. Now run: python tk_attendance_app.py")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
