# 🏠 SmartHome Automation System

A clean, modern smart home dashboard built with Flask, SQLite, Bootstrap, and JavaScript.

---

## 📁 Folder Structure

```
smarthome/
├── app.py                   # Flask backend (OOP SmartDevice classes)
├── smarthome.db             # SQLite database (auto-created on first run)
├── requirements.txt         # Python dependencies
├── templates/
│   ├── login.html           # Login page
│   └── dashboard.html       # Main dashboard
└── static/
    ├── css/
    │   └── style.css        # All styles + animations
    └── js/
        └── main.js          # Device toggle logic + UI updates
```

---

## ⚙️ Setup & Run

### 1. Install dependencies
```bash
pip install flask
```

### 2. Start the server
```bash
cd smarthome
python app.py
```

### 3. Open in browser
Visit: **http://127.0.0.1:5000**

Default credentials:
- **Username:** `admin`
- **Password:** `admin123`

---

## 🎯 Features

| Feature | Details |
|---|---|
| **Login / Logout** | Session-based auth with hashed passwords |
| **Device Control** | Toggle ON/OFF with a single click |
| **Animations** | Glowing bulb, spinning fan, shudder lock |
| **Responsive** | Mobile-friendly sidebar that collapses |
| **Live Stats** | Active device counter updates instantly |
| **Toast Notifications** | Feedback on every device action |

---

## 🧩 OOP Design

```
SmartDevice (base class)
├── Light      → get_status_label() → "ON" / "OFF"
├── Fan        → get_status_label() → "RUNNING" / "STOPPED"
└── DoorLock   → get_status_label() → "LOCKED" / "UNLOCKED"
```

Each class inherits `turn_on()`, `turn_off()`, `toggle()`, and `to_dict()` from the base.
