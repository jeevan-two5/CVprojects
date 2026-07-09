import sqlite3
import os
from pathlib import Path

# Path to the database
DB_PATH = Path("data/docusync.db")

def clear_database():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Tables to clear
        tables = ["staged_updates", "processed_prs", "pr_context"]
        
        print(f"🧹 Clearing database: {DB_PATH}")
        
        for table in tables:
            try:
                cursor.execute(f"DELETE FROM {table}")
                print(f"  ✅ Cleared table: {table}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️ Could not clear table {table}: {e}")
        
        conn.commit()
        conn.close()
        print("\n✨ Database cleared successfully!")
        
    except Exception as e:
        print(f"❌ Error clearing database: {e}")

if __name__ == "__main__":
    clear_database()
