import os
import sys
import json
import sqlite3
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "snapshots", "samples.db")


class SnapshotDB:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    vehicle_name TEXT NOT NULL,
                    vehicle_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    build_fingerprint TEXT,
                    data_json TEXT NOT NULL,
                    raw_buffer BLOB
                )
            """)
            conn.commit()

    def save_snapshot(self, name, vehicle_name, vehicle_type, data_dict, raw_buffer=None, build_fingerprint=None):
        created_at = datetime.datetime.now().isoformat()
        data_json = json.dumps(data_dict, ensure_ascii=False)
        fp_json = json.dumps(build_fingerprint, ensure_ascii=False) if build_fingerprint else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO snapshots (name, vehicle_name, vehicle_type, created_at, build_fingerprint, data_json, raw_buffer)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, vehicle_name, vehicle_type, created_at, fp_json, data_json, raw_buffer))
            conn.commit()
            return cursor.lastrowid

    def delete_snapshot(self, snapshot_id_or_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if isinstance(snapshot_id_or_name, int) or (isinstance(snapshot_id_or_name, str) and snapshot_id_or_name.isdigit()):
                cursor.execute("DELETE FROM snapshots WHERE id = ?", (int(snapshot_id_or_name),))
            else:
                cursor.execute("DELETE FROM snapshots WHERE name = ?", (str(snapshot_id_or_name),))
            conn.commit()
            return cursor.rowcount > 0

    def list_snapshots(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, vehicle_name, vehicle_type, created_at, build_fingerprint FROM snapshots ORDER BY id DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_snapshot(self, snapshot_id_or_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if isinstance(snapshot_id_or_name, int) or (isinstance(snapshot_id_or_name, str) and snapshot_id_or_name.isdigit()):
                cursor.execute("SELECT * FROM snapshots WHERE id = ?", (int(snapshot_id_or_name),))
            else:
                cursor.execute("SELECT * FROM snapshots WHERE name = ?", (str(snapshot_id_or_name),))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["data"] = json.loads(res["data_json"])
            except Exception:
                res["data"] = {}
            if res.get("build_fingerprint"):
                try:
                    res["build_fingerprint"] = json.loads(res["build_fingerprint"])
                except Exception:
                    pass
            return res

    def get_all_snapshots(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM snapshots ORDER BY id ASC")
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["data"] = json.loads(item["data_json"])
                except Exception:
                    item["data"] = {}
                result.append(item)
            return result
