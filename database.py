"""
database.py -- handles all SQLite storage and login security.
"""

import sqlite3
import hashlib
import os
import binascii
from datetime import datetime

DB_NAME = "wood_billing.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return binascii.hexlify(salt).decode() + ":" + binascii.hexlify(pwd_hash).decode()


def verify_password(stored_value: str, provided_password: str) -> bool:
    try:
        salt_hex, hash_hex = stored_value.split(":")
        salt = binascii.unhexlify(salt_hex)
        new_hash = hashlib.pbkdf2_hmac("sha256", provided_password.encode(), salt, 100000)
        return binascii.hexlify(new_hash).decode() == hash_hex
    except Exception:
        return False


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            wood_type TEXT,
            storage_loc TEXT,
            bill_date TEXT,
            vehicle_number TEXT,
            payment_status TEXT,
            payment_mode TEXT,
            weighment_fee REAL,
            reduction REAL,
            grand_total REAL,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER,
            initial_weight REAL,
            empty_weight REAL,
            total_weight REAL,
            rate REAL,
            total_cost REAL,
            FOREIGN KEY (bill_id) REFERENCES bills (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wood_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            storage_loc TEXT,
            created_at TEXT
        )
    """)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        create_user("admin", "admin123")

    # Wood types: these three always exist; old demo types are removed
    # so the change takes effect even on an existing database.
    for old_name in ("Teak", "Rosewood", "Pine", "Neem"):
        cur.execute("DELETE FROM wood_types WHERE name = ?", (old_name,))
    for name, loc in [("Palajadhi", "Yard 1"),
                      ("Puli", "Yard 2"),
                      ("Other", "Yard 3")]:
        cur.execute(
            "INSERT OR IGNORE INTO wood_types (name, storage_loc, created_at) "
            "VALUES (?, ?, ?)",
            (name, loc, datetime.now().isoformat()),
        )
    conn.commit()

    cur.execute("PRAGMA table_info(bills)")
    existing_cols = [row[1] for row in cur.fetchall()]
    for col in ("vehicle_number", "payment_status"):
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE bills ADD COLUMN {col} TEXT")
    conn.commit()

    conn.close()


def create_user(username: str, password: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), datetime.now().isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def verify_user(username: str, password: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return False
    return verify_password(row["password_hash"], password)


def add_customer(name: str, phone: str = "", address: str = "") -> bool:
    if not name.strip():
        return False
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO customers (name, phone, address, created_at) VALUES (?, ?, ?, ?)",
        (name.strip(), phone.strip(), address.strip(), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return True


def get_all_customers():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, phone, address FROM customers ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_customer_names():
    return [c["name"] for c in get_all_customers()]


def add_wood_type(name: str, storage_loc: str = "") -> bool:
    if not name.strip():
        return False
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO wood_types (name, storage_loc, created_at) VALUES (?, ?, ?)",
            (name.strip(), storage_loc.strip(), datetime.now().isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_all_wood_types():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, storage_loc FROM wood_types ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_storage_for_wood(name: str) -> str:
    for w in get_all_wood_types():
        if w["name"] == name:
            return w["storage_loc"] or "(no location set)"
    return "(unknown)"


def save_bill(customer_name, wood_type, storage_loc, bill_date,
               vehicle_number, payment_status, payment_mode,
               weighment_fee, reduction, grand_total, rows):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bills
           (customer_name, wood_type, storage_loc, bill_date,
            vehicle_number, payment_status, payment_mode,
            weighment_fee, reduction, grand_total, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_name, wood_type, storage_loc, str(bill_date),
         vehicle_number, payment_status, payment_mode,
         weighment_fee, reduction, grand_total, datetime.now().isoformat()),
    )
    bill_id = cur.lastrowid
    for r in rows:
        cur.execute(
            """INSERT INTO bill_items
               (bill_id, initial_weight, empty_weight, total_weight, rate, total_cost)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (bill_id, r["initial_weight"], r["empty_weight"],
             r["total_weight"], r["rate"], r["total_cost"]),
        )
    conn.commit()
    conn.close()
    return bill_id


if __name__ == "__main__":
    init_db()
    print(f"Database '{DB_NAME}' is ready.")
    print("Default login -> username: admin   password: admin123")