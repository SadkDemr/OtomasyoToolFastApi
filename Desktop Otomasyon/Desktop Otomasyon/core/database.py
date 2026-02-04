import sqlite3
import json
import os
import logging
from core.scenario import Scenario, Action

from core.config import DB_PATH

class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.logger = logging.getLogger("DatabaseManager")
        self._initialize_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_db(self):
        """Tables initialization"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Scenarios table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scenarios (
                        id INTEGER PRIMARY KEY AUTO_INCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Actions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS actions (
                        id INTEGER PRIMARY KEY AUTO_INCREMENT,
                        scenario_id INTEGER,
                        type TEXT NOT NULL,
                        params TEXT,
                        description TEXT,
                        order_index INTEGER,
                        FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
                    )
                """)
                conn.commit()
            self.logger.info("Database initialized successfully.")
        except Exception as e:
            # SQLite doesn't support AUTO_INCREMENT keyword exactly like this, it's AUTOINCREMENT for INTEGER PRIMARY KEY
            # Actually INTEGER PRIMARY KEY in SQLite is already auto-increment.
            # Let's fix the syntax for standard SQLite
            self._fix_initialization()

    def _fix_initialization(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scenarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scenario_id INTEGER,
                        type TEXT NOT NULL,
                        params TEXT,
                        description TEXT,
                        order_index INTEGER,
                        FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS assets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")

    def save_scenario(self, scenario: Scenario):
        """Saves a scenario and its actions to the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Insert scenario
                cursor.execute(
                    "INSERT INTO scenarios (name, description) VALUES (?, ?)",
                    (scenario.name, scenario.description)
                )
                scenario_id = cursor.lastrowid
                
                # Insert actions
                for idx, action in enumerate(scenario.actions):
                    cursor.execute(
                        "INSERT INTO actions (scenario_id, type, params, description, order_index) VALUES (?, ?, ?, ?, ?)",
                        (scenario_id, action.type, json.dumps(action.params), action.description, idx)
                    )
                conn.commit()
                return scenario_id
        except Exception as e:
            self.logger.error(f"Error saving scenario: {e}")
            return None

    def list_scenarios(self):
        """Returns a list of all scenarios."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, description, created_at FROM scenarios ORDER BY created_at DESC")
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Error listing scenarios: {e}")
            return []

    def load_scenario_by_id(self, scenario_id):
        """Loads a full Scenario object by ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Get scenario info
                cursor.execute("SELECT name, description FROM scenarios WHERE id = ?", (scenario_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                
                scenario = Scenario(name=row[0], description=row[1])
                
                # Get actions
                cursor.execute(
                    "SELECT type, params, description FROM actions WHERE scenario_id = ? ORDER BY order_index ASC",
                    (scenario_id,)
                )
                for action_row in cursor.fetchall():
                    scenario.add_action(Action(
                        type=action_row[0],
                        params=json.loads(action_row[1]),
                        description=action_row[2]
                    ))
                return scenario
        except Exception as e:
            self.logger.error(f"Error loading scenario: {e}")
            return None

    def delete_scenario(self, scenario_id):
        """Deletes a scenario from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Error deleting scenario: {e}")
            return False

    # --- Asset Management ---
    def save_asset(self, name, file_path):
        """Saves a new asset record."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO assets (name, file_path) VALUES (?, ?)",
                    (name, file_path)
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Error saving asset: {e}")
            return None

    def list_assets(self):
        """Returns all assets."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, file_path, created_at FROM assets ORDER BY created_at DESC")
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Error listing assets: {e}")
            return []

    def delete_asset(self, asset_id):
        """Deletes an asset from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Error deleting asset: {e}")
            return False
