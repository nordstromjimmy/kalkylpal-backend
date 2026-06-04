"""
migrate_chat.py — Run once to create the chat_messages table.

Usage:
    cd backend
    python migrate_chat.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("vvs_app.db")

def migrate():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH} — run the app first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if table already exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'")
    if cursor.fetchone():
        print("Nothing to do — chat_messages table already exists.")
        conn.close()
        return

    cursor.execute("""
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX ix_chat_messages_project_id ON chat_messages (project_id)")

    conn.commit()
    conn.close()
    print("✓ Created chat_messages table")

if __name__ == "__main__":
    migrate()