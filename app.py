"""
Smart Home Automation System — Extensions
Adds: Scenes, Scheduling, and Energy Usage Tracking

Drop this file next to app.py and:
    from extensions import (
        init_extension_tables,
        Scene, get_all_scenes, get_scene, create_scene, apply_scene, delete_scene,
        Schedule, get_all_schedules, create_schedule, delete_schedule, run_due_schedules,
        EnergyTracker, log_status_change, get_energy_summary,
        register_extension_routes,
    )

Then in app.py:
    init_extension_tables()                 # call once, alongside init_db()
    register_extension_routes(app)          # registers /api/scenes, /api/schedules, /api/energy/*

This module reuses your existing get_db(), build_device(), and
update_device_status() from app.py rather than redefining them, so it stays
in sync with your single source of truth for devices.
"""

import json
import time
from datetime import datetime, timedelta

# Imported lazily inside functions to avoid circular-import issues at module
# load time (extensions.py is imported BY app.py).
def _app():
    import app as _app_module
    return _app_module


# ─────────────────────────────────────────────
#  Table setup
# ─────────────────────────────────────────────

def init_extension_tables():
    """Create the extra tables this module needs. Call once at startup."""
    conn = _app().get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scenes (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scene_devices (
            scene_id  INTEGER NOT NULL,
            device_id INTEGER NOT NULL,
            status    INTEGER NOT NULL,
            PRIMARY KEY (scene_id, device_id),
            FOREIGN KEY (scene_id)  REFERENCES scenes(id)  ON DELETE CASCADE,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   INTEGER,
            scene_id    INTEGER,
            action      TEXT NOT NULL,      -- 'on', 'off', or 'scene'
            time_of_day TEXT NOT NULL,      -- 'HH:MM' 24-hour
            days        TEXT NOT NULL,      -- CSV of weekday ints, 0=Mon ... 6=Sun ("" = every day)
            enabled     INTEGER DEFAULT 1,
            last_run    TEXT,               -- ISO timestamp of last execution, or NULL
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (scene_id)  REFERENCES scenes(id)  ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS energy_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            status    INTEGER NOT NULL,     -- state the device CHANGED TO
            timestamp TEXT NOT NULL,        -- ISO timestamp of the change
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
#  Scenes
# ─────────────────────────────────────────────

class Scene:
    """A named snapshot of desired states for a set of devices."""

    def __init__(self, scene_id, name, device_states=None):
        self.scene_id = scene_id
        self.name = name
        # device_states: list of {"device_id": int, "status": bool}
        self.device_states = device_states or []

    def to_dict(self):
        return {
            "id": self.scene_id,
            "name": self.name,
            "devices": self.device_states,
        }


def get_all_scenes():
    conn = _app().get_db()
    scene_rows = conn.execute("SELECT id, name FROM scenes").fetchall()
    scenes = []
    for s in scene_rows:
        device_rows = conn.execute(
            "SELECT device_id, status FROM scene_devices WHERE scene_id = ?",
            (s["id"],),
        ).fetchall()
        states = [{"device_id": d["device_id"], "status": bool(d["status"])} for d in device_rows]
        scenes.append(Scene(s["id"], s["name"], states))
    conn.close()
    return scenes


def get_scene(scene_id):
    conn = _app().get_db()
    s = conn.execute("SELECT id, name FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not s:
        conn.close()
        return None
    device_rows = conn.execute(
        "SELECT device_id, status FROM scene_devices WHERE scene_id = ?",
        (scene_id,),
    ).fetchall()
    conn.close()
    states = [{"device_id": d["device_id"], "status": bool(d["status"])} for d in device_rows]
    return Scene(s["id"], s["name"], states)


def create_scene(name, device_states):
    """
    device_states: list of {"device_id": int, "status": bool}
    e.g. create_scene("Good Night", [
            {"device_id": 1, "status": False},
            {"device_id": 6, "status": True},
         ])
    """
    conn = _app().get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO scenes (name) VALUES (?)", (name,))
    scene_id = cur.lastrowid
    for ds in device_states:
        cur.execute(
            "INSERT INTO scene_devices (scene_id, device_id, status) VALUES (?, ?, ?)",
            (scene_id, ds["device_id"], 1 if ds["status"] else 0),
        )
    conn.commit()
    conn.close()
    return scene_id


def delete_scene(scene_id):
    conn = _app().get_db()
    conn.execute("DELETE FROM scene_devices WHERE scene_id = ?", (scene_id,))
    conn.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    conn.commit()
    conn.close()


def apply_scene(scene_id):
    """Push every device in the scene to its stored state. Returns list of resulting device dicts."""
    scene = get_scene(scene_id)
    if not scene:
        return None

    results = []
    for ds in scene.device_states:
        device_id = ds["device_id"]
        new_status = ds["status"]
        _app().update_device_status(device_id, new_status)
        log_status_change(device_id, new_status)

        conn = _app().get_db()
        row = conn.execute(
            "SELECT id, name, type, status FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        conn.close()
        if row:
            device = _app().build_device(tuple(row))
            results.append(device.to_dict())

    return results


# ─────────────────────────────────────────────
#  Scheduling
# ─────────────────────────────────────────────

class Schedule:
    """
    A rule that fires an action at a given time of day, on given weekdays.

    action: "on" / "off"  -> applies directly to device_id
            "scene"       -> applies the scene referenced by scene_id
    days:   list of ints, 0=Monday ... 6=Sunday. Empty list = every day.
    """

    def __init__(self, schedule_id, device_id, scene_id, action,
                 time_of_day, days, enabled=True, last_run=None):
        self.schedule_id = schedule_id
        self.device_id = device_id
        self.scene_id = scene_id
        self.action = action
        self.time_of_day = time_of_day  # "HH:MM"
        self.days = days                # list[int]
        self.enabled = enabled
        self.last_run = last_run

    def to_dict(self):
        return {
            "id": self.schedule_id,
            "device_id": self.device_id,
            "scene_id": self.scene_id,
            "action": self.action,
            "time_of_day": self.time_of_day,
            "days": self.days,
            "enabled": self.enabled,
            "last_run": self.last_run,
        }

    def is_due(self, now=None):
        """Check whether this schedule should fire right now (minute-resolution)."""
        if not self.enabled:
            return False

        now = now or datetime.now()
        current_hhmm = now.strftime("%H:%M")
        if current_hhmm != self.time_of_day:
            return False

        if self.days and now.weekday() not in self.days:
            return False

        # Avoid re-firing multiple times within the same minute if last_run
        # was already stamped for today at this time.
        if self.last_run:
            last_run_dt = datetime.fromisoformat(self.last_run)
            if last_run_dt.strftime("%Y-%m-%d %H:%M") == now.strftime("%Y-%m-%d %H:%M"):
                return False

        return True


def _row_to_schedule(row):
    days = [int(d) for d in row["days"].split(",") if d != ""] if row["days"] else []
    return Schedule(
        schedule_id=row["id"],
        device_id=row["device_id"],
        scene_id=row["scene_id"],
        action=row["action"],
        time_of_day=row["time_of_day"],
        days=days,
        enabled=bool(row["enabled"]),
        last_run=row["last_run"],
    )


def get_all_schedules():
    conn = _app().get_db()
    rows = conn.execute("SELECT * FROM schedules").fetchall()
    conn.close()
    return [_row_to_schedule(r) for r in rows]


def create_schedule(time_of_day, action, device_id=None, scene_id=None, days=None, enabled=True):
    """
    Examples:
      # Turn the porch light on at 7:00 PM every day
      create_schedule(time_of_day="19:00", action="on", device_id=1)

      # Apply "Good Night" scene at 11:00 PM, weekdays only (Mon-Fri)
      create_schedule(time_of_day="23:00", action="scene", scene_id=3, days=[0,1,2,3,4])
    """
    if action == "scene" and not scene_id:
        raise ValueError("scene_id is required when action='scene'")
    if action in ("on", "off") and not device_id:
        raise ValueError("device_id is required when action is 'on' or 'off'")

    days_csv = ",".join(str(d) for d in (days or []))
    conn = _app().get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO schedules (device_id, scene_id, action, time_of_day, days, enabled)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (device_id, scene_id, action, time_of_day, days_csv, 1 if enabled else 0),
    )
    schedule_id = cur.lastrowid
    conn.commit()
    conn.close()
    return schedule_id


def delete_schedule(schedule_id):
    conn = _app().get_db()
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def set_schedule_enabled(schedule_id, enabled):
    conn = _app().get_db()
    conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id))
    conn.commit()
    conn.close()


def _mark_schedule_ran(schedule_id, when):
    conn = _app().get_db()
    conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (when.isoformat(), schedule_id))
    conn.commit()
    conn.close()


def run_due_schedules(now=None):
    """
    Check all enabled schedules and execute the ones that are due right now.
    Call this once a minute, e.g. from a background thread or APScheduler job:

        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler()
        sched.add_job(run_due_schedules, "interval", minutes=1)
        sched.start()

    Returns a list of {"schedule_id": ..., "result": ...} for whatever fired.
    """
    now = now or datetime.now()
    fired = []

    for sched in get_all_schedules():
        if not sched.is_due(now):
            continue

        if sched.action == "scene":
            result = apply_scene(sched.scene_id)
        else:
            new_status = (sched.action == "on")
            _app().update_device_status(sched.device_id, new_status)
            log_status_change(sched.device_id, new_status)

            conn = _app().get_db()
            row = conn.execute(
                "SELECT id, name, type, status FROM devices WHERE id = ?",
                (sched.device_id,),
            ).fetchone()
            conn.close()
            result = _app().build_device(tuple(row)).to_dict() if row else None

        _mark_schedule_ran(sched.schedule_id, now)
        fired.append({"schedule_id": sched.schedule_id, "result": result})

    return fired


# ─────────────────────────────────────────────
#  Energy tracking
# ─────────────────────────────────────────────

# Rough average wattage by device type, used to ESTIMATE consumption.
# Override per-device if you want more accurate numbers.
DEVICE_WATTAGE = {
    "light":    9,     # modern LED bulb
    "fan":      60,    # ceiling fan
    "doorlock": 2,     # smart lock standby/actuation draw
}


class EnergyTracker:
    """Computes estimated energy usage from the on/off history of a device."""

    def __init__(self, device_id, device_type):
        self.device_id = device_id
        self.device_type = device_type
        self.watts = DEVICE_WATTAGE.get(device_type, 10)

    def estimate_kwh(self, on_seconds):
        """Convert seconds-on into estimated kilowatt-hours."""
        hours = on_seconds / 3600
        return round((self.watts * hours) / 1000, 4)


def log_status_change(device_id, new_status):
    """Record a status change with a timestamp. Call this anywhere a device's
    state changes (toggle, scene apply, schedule fire) to keep energy stats accurate."""
    conn = _app().get_db()
    conn.execute(
        "INSERT INTO energy_log (device_id, status, timestamp) VALUES (?, ?, ?)",
        (device_id, 1 if new_status else 0, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def _seconds_on_in_window(events, window_start, window_end):
    """
    events: list of (timestamp: datetime, status: bool), sorted ascending,
            already filtered to a single device.
    Computes total seconds the device was ON within [window_start, window_end),
    assuming OFF before the first known event.
    """
    total = timedelta()
    current_status = False
    current_since = window_start

    for ts, status in events:
        if ts < window_start:
            current_status = status
            current_since = window_start
            continue
        if ts > window_end:
            break
        if current_status:
            total += ts - current_since
        current_status = status
        current_since = ts

    if current_status:
        total += window_end - current_since

    return total.total_seconds()


def get_energy_summary(days=7):
    """
    Returns per-device and total estimated energy usage (kWh) over the last
    `days` days, based on logged status changes.

    {
      "window_days": 7,
      "devices": [
        {"device_id": 1, "name": "Living Room Light", "type": "light",
         "estimated_kwh": 0.42, "hours_on": 46.7},
        ...
      ],
      "total_estimated_kwh": 1.95
    }
    """
    conn = _app().get_db()
    devices = conn.execute("SELECT id, name, type FROM devices").fetchall()

    window_end = datetime.now()
    window_start = window_end - timedelta(days=days)

    device_summaries = []
    total_kwh = 0.0

    for d in devices:
        rows = conn.execute(
            """SELECT status, timestamp FROM energy_log
               WHERE device_id = ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (d["id"], window_end.isoformat()),
        ).fetchall()

        events = [(datetime.fromisoformat(r["timestamp"]), bool(r["status"])) for r in rows]
        seconds_on = _seconds_on_in_window(events, window_start, window_end)

        tracker = EnergyTracker(d["id"], d["type"])
        kwh = tracker.estimate_kwh(seconds_on)
        total_kwh += kwh

        device_summaries.append({
            "device_id": d["id"],
            "name": d["name"],
            "type": d["type"],
            "estimated_kwh": kwh,
            "hours_on": round(seconds_on / 3600, 2),
        })

    conn.close()

    return {
        "window_days": days,
        "devices": sorted(device_summaries, key=lambda x: -x["estimated_kwh"]),
        "total_estimated_kwh": round(total_kwh, 4),
    }


# ─────────────────────────────────────────────
#  Flask route registration
# ─────────────────────────────────────────────

def register_extension_routes(app):
    """
    Call register_extension_routes(app) from app.py after creating the Flask
    app, to wire up /api/scenes, /api/schedules, and /api/energy/* endpoints.
    Reuses the same @login_required decorator app.py already defines.
    """
    from flask import request, jsonify
    login_required = _app().login_required

    # ---- Scenes ----

    @app.route("/api/scenes", methods=["GET"])
    @login_required
    def list_scenes():
        return jsonify([s.to_dict() for s in get_all_scenes()])

    @app.route("/api/scenes", methods=["POST"])
    @login_required
    def create_scene_route():
        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        device_states = data.get("devices", [])
        if not name:
            return jsonify({"error": "Scene name is required"}), 400
        if not device_states:
            return jsonify({"error": "At least one device state is required"}), 400
        scene_id = create_scene(name, device_states)
        return jsonify(get_scene(scene_id).to_dict()), 201

    @app.route("/api/scenes/<int:scene_id>", methods=["DELETE"])
    @login_required
    def delete_scene_route(scene_id):
        delete_scene(scene_id)
        return jsonify({"deleted": scene_id})

    @app.route("/api/scenes/<int:scene_id>/apply", methods=["POST"])
    @login_required
    def apply_scene_route(scene_id):
        result = apply_scene(scene_id)
        if result is None:
            return jsonify({"error": "Scene not found"}), 404
        return jsonify({"applied": scene_id, "devices": result})

    # ---- Schedules ----

    @app.route("/api/schedules", methods=["GET"])
    @login_required
    def list_schedules():
        return jsonify([s.to_dict() for s in get_all_schedules()])

    @app.route("/api/schedules", methods=["POST"])
    @login_required
    def create_schedule_route():
        data = request.get_json(force=True)
        try:
            schedule_id = create_schedule(
                time_of_day=data["time_of_day"],
                action=data["action"],
                device_id=data.get("device_id"),
                scene_id=data.get("scene_id"),
                days=data.get("days", []),
                enabled=data.get("enabled", True),
            )
        except (KeyError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"id": schedule_id}), 201

    @app.route("/api/schedules/<int:schedule_id>", methods=["DELETE"])
    @login_required
    def delete_schedule_route(schedule_id):
        delete_schedule(schedule_id)
        return jsonify({"deleted": schedule_id})

    @app.route("/api/schedules/<int:schedule_id>/toggle", methods=["POST"])
    @login_required
    def toggle_schedule_route(schedule_id):
        data = request.get_json(force=True) or {}
        enabled = data.get("enabled", True)
        set_schedule_enabled(schedule_id, enabled)
        return jsonify({"id": schedule_id, "enabled": enabled})

    @app.route("/api/schedules/run-due", methods=["POST"])
    @login_required
    def run_due_schedules_route():
        """Manual trigger for testing; in production call run_due_schedules()
        from a background scheduler instead of an HTTP endpoint."""
        fired = run_due_schedules()
        return jsonify({"fired": fired})

    # ---- Energy ----

    @app.route("/api/energy/summary", methods=["GET"])
    @login_required
    def energy_summary_route():
        days = request.args.get("days", default=7, type=int)
        return jsonify(get_energy_summary(days=days))
