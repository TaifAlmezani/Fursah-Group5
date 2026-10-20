from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db.database import init_db

def main():
    print(f"Initializing SQLite database at: {settings.db_path}")
    init_db(settings.db_path, settings.seed_path)
    print("Database initialized and seeded with assets successfully.")

if __name__ == "__main__":
    main()
