"""
One-time helper script to create/update staff accounts.

Usage:
  python create_accounts.py
"""

from database import create_account

def main():
    create_account("admin2", "Admin@123", "admin")
    create_account("teacher2", "Teacher@123", "teacher")
    print("Done. Accounts created/updated.")

if __name__ == "__main__":
    main()
