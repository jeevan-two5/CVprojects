# Script to print data from the database
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("data/docusync.db")

def dump_db():
    if not DB_PATH.exists():
        print(f"[!] Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    print("\n" + "="*60)
    print("TABLE: staged_updates")
    print("="*60)
    rows = conn.execute("SELECT * FROM staged_updates").fetchall()
    if not rows:
        print(" (empty)")
    for row in rows:
        print(f"ID: {row['id']} | PR #{row['pr_number']} | Action: {row['action']} | Created: {row['created_at']}")
        kwargs = json.loads(row['kwargs_json'])
        print(f"  Kwargs: {json.dumps(kwargs, indent=4)}")
        print("-" * 30)

    print("\n" + "="*60)
    print("TABLE: processed_prs")
    print("="*60)
    rows = conn.execute("SELECT * FROM processed_prs").fetchall()
    if not rows:
        print(" (empty)")
    for row in rows:
        print(f"SHA: {row['sha']} | Processed At: {row['processed_at']}")

    conn.close()

if __name__ == "__main__":
    dump_db()
