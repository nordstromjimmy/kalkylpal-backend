import sqlite3
from pathlib import Path

DB_PATH = Path("vvs_app.db")

NEW_COLUMNS = [
    ("client",           "TEXT"),
    ("project_number",   "TEXT"),
    ("location",         "TEXT"),
    ("tender_deadline",  "TEXT"),
    ("contact_person",   "TEXT"),
    ("notes",            "TEXT"),
]

def migrate():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH} — run the app first to create it.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}

    added = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}")
            added.append(col_name)

    conn.commit()
    conn.close()

    if added:
        print(f"✓ Added columns: {', '.join(added)}")
    else:
        print("Nothing to do — all columns already exist.")

if __name__ == "__main__":
    migrate()