# This file manages SQLite schema creation and database operations for conference registrations.
import json
import sqlite3
import uuid
from pathlib import Path
from sqlite3 import Row


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "conference.db"


def ensure_column(con: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    existing_columns = {
        row[1]
        for row in con.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name in existing_columns:
        return
    con.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_database() -> None:
    with sqlite3.connect(DATABASE_PATH) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS registrations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration_code TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                company_or_university TEXT NOT NULL,
                role TEXT NOT NULL,
                ticket_type TEXT NOT NULL,
                selected_days TEXT NOT NULL,
                workshop_preference TEXT NOT NULL,
                dietary_preference TEXT NOT NULL,
                accessibility_needs TEXT,
                status TEXT NOT NULL,
                jotform_submission_id TEXT,
                jotform_sync_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        ensure_column(con, "registrations", "jotform_submission_id", "TEXT")
        ensure_column(con, "registrations", "jotform_sync_status", "TEXT")
        con.execute(
            """CREATE TABLE IF NOT EXISTS registration_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                previous_value TEXT,
                new_value TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (registration_id) REFERENCES registrations(id)
            )"""
        )
        ensure_column(con, "registration_events", "previous_value", "TEXT")
        ensure_column(con, "registration_events", "new_value", "TEXT")


def create_registration(
    reg_code: str,
    full_name: str,
    email: str,
    organization: str,
    role: str,
    ticket_type: str,
    days: str,
    workshop: str,
    diet: str,
    access_needs: str | None,
    status: str,
    created_at: str,
    updated_at: str,
) -> int:
    with sqlite3.connect(DATABASE_PATH) as con:
        cur = con.execute(
            """INSERT INTO registrations(
                registration_code,
                full_name,
                email,
                company_or_university,
                role,
                ticket_type,
                selected_days,
                workshop_preference,
                dietary_preference,
                accessibility_needs,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reg_code,
                full_name,
                email,
                organization,
                role,
                ticket_type,
                days,
                workshop,
                diet,
                access_needs,
                status,
                created_at,
                updated_at,
            ),
        )
        if cur.lastrowid is None:
            raise RuntimeError("Registration was inserted, but SQLite did not return a row id.")
        return cur.lastrowid


def update_registration_jotform_sync(
    registration_id: int,
    jotform_submission_id: str | None,
    jotform_sync_status: str,
) -> None:
    with sqlite3.connect(DATABASE_PATH) as con:
        con.execute(
            """UPDATE registrations
            SET jotform_submission_id = ?, jotform_sync_status = ?
            WHERE id = ?""",
            (
                jotform_submission_id,
                jotform_sync_status,
                registration_id,
            ),
        )


def update_registration(
    registration_id: int,
    full_name: str,
    email: str,
    organization: str,
    role: str,
    ticket_type: str,
    days: str,
    workshop: str,
    diet: str,
    access_needs: str | None,
    status: str,
    updated_at: str,
) -> None:
    with sqlite3.connect(DATABASE_PATH) as con:
        con.execute(
            """UPDATE registrations
            SET
                full_name = ?,
                email = ?,
                company_or_university = ?,
                role = ?,
                ticket_type = ?,
                selected_days = ?,
                workshop_preference = ?,
                dietary_preference = ?,
                accessibility_needs = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                full_name,
                email,
                organization,
                role,
                ticket_type,
                days,
                workshop,
                diet,
                access_needs,
                status,
                updated_at,
                registration_id,
            ),
        )


def create_registration_event(
    registration_id: int,
    event_type: str,
    event_data: dict,
    created_at: str,
) -> int:
    with sqlite3.connect(DATABASE_PATH) as con:
        existing_columns = {row[1] for row in con.execute("PRAGMA table_info(registration_events)")}
        serialized_event_data = json.dumps(event_data, ensure_ascii=True, sort_keys=True)
        if "event_data" in existing_columns:
            cur = con.execute(
                """INSERT INTO registration_events(
                    registration_id,
                    event_type,
                    event_data,
                    created_at
                )
                VALUES (?, ?, ?, ?)""",
                (
                    registration_id,
                    event_type,
                    serialized_event_data,
                    created_at,
                ),
            )
        else:
            cur = con.execute(
                """INSERT INTO registration_events(
                    registration_id,
                    event_type,
                    previous_value,
                    new_value,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)""",
                (
                    registration_id,
                    event_type,
                    None,
                    serialized_event_data,
                    created_at,
                ),
            )
        if cur.lastrowid is None:
            raise RuntimeError("Registration event was inserted, but SQLite did not return a row id.")
        return cur.lastrowid


def find_registration_by_code_and_email(registration_code: str, email: str) -> dict | None:
    with sqlite3.connect(DATABASE_PATH) as con:
        con.row_factory = Row
        row = con.execute(
            """SELECT
                id,
                registration_code,
                full_name,
                email,
                company_or_university,
                role,
                ticket_type,
                selected_days,
                workshop_preference,
                dietary_preference,
                accessibility_needs,
                status,
                jotform_submission_id,
                jotform_sync_status,
                created_at,
                updated_at
            FROM registrations
            WHERE registration_code = ? AND lower(email) = lower(?)""",
            (registration_code, email),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def generate_registration_code() -> str:
    return f"REG-{str(uuid.uuid4())[:8]}".upper()
