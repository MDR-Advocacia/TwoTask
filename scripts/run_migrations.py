import os
import sqlite3
from pathlib import Path
from alembic import command
from alembic.config import Config

from app.db.session import SQLALCHEMY_DATABASE_URL


def reset_alembic_version_if_needed() -> None:
    """Reset alembic_version table if it contains invalid revisions."""
    # Extract database path from SQLAlchemy URL
    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")

    if not os.path.exists(db_path):
        print(f"Database {db_path} does not exist, will be created by migrations")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if alembic_version table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        if not cursor.fetchone():
            print("alembic_version table does not exist (new database)")
            conn.close()
            return

        # Get current version
        cursor.execute("SELECT version_num FROM alembic_version")
        versions = cursor.fetchall()

        if versions:
            current_version = versions[0][0]
            print(f"Current alembic version: {current_version}")

            # Check if this revision exists in migration files
            migration_dir = Path("alembic/versions")
            existing_revisions = set()

            for migration_file in migration_dir.glob("*.py"):
                if migration_file.name.startswith("__"):
                    continue
                content = migration_file.read_text()
                # Extract revision ID from file
                for line in content.split("\n"):
                    if line.startswith('revision:'):
                        rev_id = line.split('"')[1]
                        existing_revisions.add(rev_id)
                        break

            if current_version not in existing_revisions:
                print(f"WARNING: Current version '{current_version}' not found in migrations")
                print(f"Available revisions: {sorted(existing_revisions)}")
                print(f"Resetting alembic_version table...")

                # Clear the invalid version
                cursor.execute("DELETE FROM alembic_version")
                conn.commit()
                print("alembic_version table reset")

        conn.close()
    except Exception as e:
        print(f"Error checking alembic_version: {e}")
        print("Continuing with migration anyway...")


def main() -> None:
    reset_alembic_version_if_needed()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
