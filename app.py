"""
Smart Home Automation System
Flask backend with OOP design and SQLite storage
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import hashlib
import os

app = Flask(__name__)
app.secret_key = "smarthome_secret_key_2024"

# ─────────────────────────────────────────────
#  OOP: Base SmartDevice class + derived classes
# ─────────────────────────────────────────────

class SmartDevice:
    """Base class for all smart home devices."""

    def __init__(self, device_id, name, device_type, status=False):
        self.device_id   = device_id
        self.name        = name
        self.device_type = device_type   # 'light', 'fan', or 'doorlock'
        self.status      = status        # True = ON/Locked, False = OFF/Unlocked

    def turn_on(self):
        self.status = True

    def turn_off(self):
        self.status = False

    def toggle(self):
        self.status = not self.status

    def get_status_label(self):
        return "ON" if self.status else "OFF"

    def to_dict(self):
        return {
            "id":          self.device_id,
            "name":        self.name,
            "type":        self.device_type,
            "status":      self.status,
            "statusLabel": self.get_status_label(),
        }


class Light(SmartDevice):
    """Derived class representing a smart light bulb."""

    def __init__(self, device_id, name, status=False):
        super().__init__(device_id, name, device_type="light", status=status)

    def get_status_label(self):
        return "ON" if self.status else "OFF"


class Fan(SmartDevice):
    """Derived class representing a smart ceiling fan."""

    def __init__(self, device_id, name, status=False):
        super().__init__(device_id, name, device_type="fan", status=status)

    def get_status_label(self):
        return "RUNNING" if self.status else "STOPPED"


class DoorLock(SmartDevice):
    """Derived class representing a smart door lock."""

    def __init__(self, device_id, name, status=False):
        # For DoorLock: True = LOCKED, False = UNLOCKED
        super().__init__(device_id, name, device_type="doorlock", status=status)

    def get_status_label(self):
        return "LOCKED" if self.status else "UNLOCKED"


# ─────────────────────────────────────────────
#  Device factory: build the right subclass
# ─────────────────────────────────────────────

def build_device(row):
    """Given a DB row (id, name, type, status), return the correct subclass."""
    device_id, name, device_type, status = row
    status = bool(status)
    if device_type == "light":
        return Light(device_id, name, status)
    elif device_type == "fan":
        return Fan(device_id, name, status)
    elif device_type == "doorlock":
        return DoorLock(device_id, name, status)
    else:
        return SmartDevice(device_id, name, device_type, status)


# ─────────────────────────────────────────────
#  Database helpers
# ─────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "smarthome.db")


def get_db():
    """Open a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and seed default data if the database is fresh."""
    conn = get_db()
    cur  = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL
        )
    """)

    # Devices table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT    NOT NULL,
            type   TEXT    NOT NULL,
            status INTEGER DEFAULT 0
        )
    """)

    # Seed a default admin user (password: admin123)
    hashed = hashlib.sha256("admin123".encode()).hexdigest()
    cur.execute(
        "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
        ("admin", hashed)
    )

    # Seed default devices
    default_devices = [
        ("Living Room Light",  "light"),
        ("Bedroom Light",      "light"),
        ("Kitchen Light",      "light"),
        ("Ceiling Fan",        "fan"),
        ("Bedroom Fan",        "fan"),
        ("Front Door Lock",    "doorlock"),
        ("Back Door Lock",     "doorlock"),
    ]
    for name, dtype in default_devices:
        cur.execute(
            "INSERT OR IGNORE INTO devices (name, type) VALUES (?, ?)",
            (name, dtype)
        )

    conn.commit()
    conn.close()


def get_all_devices():
    """Return a list of SmartDevice subclass instances from the DB."""
    conn = get_db()
    rows = conn.execute("SELECT id, name, type, status FROM devices").fetchall()
    conn.close()
    return [build_device(tuple(r)) for r in rows]


def update_device_status(device_id, new_status):
    """Persist a device's ON/OFF status to the database."""
    conn = get_db()
    conn.execute(
        "UPDATE devices SET status = ? WHERE id = ?",
        (1 if new_status else 0, device_id)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
#  Auth helpers
# ─────────────────────────────────────────────

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def verify_user(username, password):
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, hash_password(password))
    ).fetchone()
    conn.close()
    return row is not None


def login_required(f):
    """Simple decorator to protect routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if verify_user(username, password):
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    devices = get_all_devices()
    # Separate devices by type for the template
    lights    = [d for d in devices if d.device_type == "light"]
    fans      = [d for d in devices if d.device_type == "fan"]
    doorlocks = [d for d in devices if d.device_type == "doorlock"]

    # Quick stats
    stats = {
        "total":   len(devices),
        "active":  sum(1 for d in devices if d.status),
        "lights":  len(lights),
        "fans":    len(fans),
        "locks":   len(doorlocks),
    }
    return render_template(
        "dashboard.html",
        username=session["user"],
        lights=lights,
        fans=fans,
        doorlocks=doorlocks,
        stats=stats,
    )


@app.route("/api/toggle/<int:device_id>", methods=["POST"])
@login_required
def toggle_device(device_id):
    """API endpoint: toggle a device and return its new state as JSON."""
    conn   = get_db()
    row    = conn.execute(
        "SELECT id, name, type, status FROM devices WHERE id = ?", (device_id,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Device not found"}), 404

    device = build_device(tuple(row))
    device.toggle()
    update_device_status(device_id, device.status)

    return jsonify(device.to_dict())


@app.route("/api/devices")
@login_required
def api_devices():
    """Return all devices as JSON."""
    devices = get_all_devices()
    return jsonify([d.to_dict() for d in devices])


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
