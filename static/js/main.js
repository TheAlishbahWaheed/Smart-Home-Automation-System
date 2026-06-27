/**
 * SmartHome – main.js
 * Handles device toggle API calls, DOM updates, and animations.
 */

// ─────────────────────────────────────────────
//  Clock in topbar
// ─────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById("currentTime");
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
updateClock();
setInterval(updateClock, 30_000);


// ─────────────────────────────────────────────
//  Sidebar toggle (mobile)
// ─────────────────────────────────────────────
function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
}

// Close sidebar when clicking outside on mobile
document.addEventListener("click", (e) => {
  const sidebar = document.getElementById("sidebar");
  const toggle  = document.querySelector(".sidebar-toggle");
  if (
    sidebar &&
    sidebar.classList.contains("open") &&
    !sidebar.contains(e.target) &&
    !toggle.contains(e.target)
  ) {
    sidebar.classList.remove("open");
  }
});


// ─────────────────────────────────────────────
//  Toast helper
// ─────────────────────────────────────────────
function showToast(message, success = true) {
  const toastEl = document.getElementById("liveToast");
  const toastMsg = document.getElementById("toastMsg");
  if (!toastEl || !toastMsg) return;

  toastMsg.textContent = message;
  // Colour the toast border to match outcome
  toastEl.style.borderColor = success
    ? "rgba(34,197,94,0.4)"
    : "rgba(239,68,68,0.4)";

  const bsToast = bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2500 });
  bsToast.show();
}


// ─────────────────────────────────────────────
//  Update active-device counter in stats row
// ─────────────────────────────────────────────
function updateActiveCount(delta) {
  const el = document.getElementById("statActive");
  if (!el) return;
  const current = parseInt(el.textContent, 10) || 0;
  el.textContent = Math.max(0, current + delta);
}


// ─────────────────────────────────────────────
//  DOM update helpers per device type
// ─────────────────────────────────────────────

function applyLightState(id, isOn) {
  const card  = document.getElementById(`card-${id}`);
  const badge = document.getElementById(`badge-${id}`);
  const btn   = document.getElementById(`btn-${id}`);
  if (!card) return;

  if (isOn) {
    card.classList.add("active");
    badge.className   = "device-status-badge on";
    badge.textContent = "ON";
    btn.className     = "toggle-btn btn-on";
    btn.innerHTML     = '<i class="fa-solid fa-toggle-on"></i><span>Turn Off</span>';
  } else {
    card.classList.remove("active");
    badge.className   = "device-status-badge off";
    badge.textContent = "OFF";
    btn.className     = "toggle-btn btn-off";
    btn.innerHTML     = '<i class="fa-solid fa-toggle-off"></i><span>Turn On</span>';
  }
}

function applyFanState(id, isOn) {
  const card      = document.getElementById(`card-${id}`);
  const badge     = document.getElementById(`badge-${id}`);
  const btn       = document.getElementById(`btn-${id}`);
  const iconWrap  = document.getElementById(`icon-${id}`);
  if (!card) return;

  if (isOn) {
    card.classList.add("active");
    iconWrap.classList.add("spinning");
    badge.className   = "device-status-badge on";
    badge.textContent = "RUNNING";
    btn.className     = "toggle-btn btn-on";
    btn.innerHTML     = '<i class="fa-solid fa-toggle-on"></i><span>Stop Fan</span>';
  } else {
    card.classList.remove("active");
    iconWrap.classList.remove("spinning");
    badge.className   = "device-status-badge off";
    badge.textContent = "STOPPED";
    btn.className     = "toggle-btn btn-off";
    btn.innerHTML     = '<i class="fa-solid fa-toggle-off"></i><span>Start Fan</span>';
  }
}

function applyLockState(id, isLocked) {
  const card     = document.getElementById(`card-${id}`);
  const badge    = document.getElementById(`badge-${id}`);
  const btn      = document.getElementById(`btn-${id}`);
  const lockIco  = document.getElementById(`lockico-${id}`);
  const lockTxt  = document.getElementById(`lockbtn-txt-${id}`);
  const btnIco   = document.getElementById(`lockbtn-ico-${id}`);
  const iconWrap = document.getElementById(`icon-${id}`);
  if (!card) return;

  // Shudder animation on the icon
  iconWrap.classList.remove("shudder");
  void iconWrap.offsetWidth;               // reflow to restart animation
  iconWrap.classList.add("shudder");

  if (isLocked) {
    card.classList.add("locked");
    badge.className   = "device-status-badge locked";
    badge.textContent = "LOCKED";
    btn.className     = "toggle-btn btn-locked";
    if (lockIco)  lockIco.className = "fa-solid fa-lock";
    if (btnIco)   btnIco.className  = "fa-solid fa-lock-open";
    if (lockTxt)  lockTxt.textContent = "Unlock";
  } else {
    card.classList.remove("locked");
    badge.className   = "device-status-badge unlocked";
    badge.textContent = "UNLOCKED";
    btn.className     = "toggle-btn btn-unlocked";
    if (lockIco)  lockIco.className = "fa-solid fa-lock-open";
    if (btnIco)   btnIco.className  = "fa-solid fa-lock";
    if (lockTxt)  lockTxt.textContent = "Lock";
  }
}


// ─────────────────────────────────────────────
//  Main toggle function (called by HTML buttons)
// ─────────────────────────────────────────────

async function toggleDevice(deviceId, deviceType) {
  const btn = document.getElementById(`btn-${deviceId}`);

  // Disable button during request to prevent double-clicks
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/api/toggle/${deviceId}`, { method: "POST" });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();       // { id, name, type, status, statusLabel }
    const isOn = data.status;            // boolean

    // Apply visual state based on device type
    if (deviceType === "light") {
      applyLightState(deviceId, isOn);
      showToast(`💡 ${data.name} turned ${isOn ? "ON" : "OFF"}`);
    } else if (deviceType === "fan") {
      applyFanState(deviceId, isOn);
      showToast(`🌀 ${data.name} ${isOn ? "started" : "stopped"}`);
    } else if (deviceType === "doorlock") {
      applyLockState(deviceId, isOn);
      showToast(`🔐 ${data.name} ${isOn ? "locked" : "unlocked"}`);
    }

    // Update the active device counter
    updateActiveCount(isOn ? 1 : -1);

  } catch (err) {
    console.error("Toggle failed:", err);
    showToast("⚠️ Could not reach the device.", false);
  } finally {
    if (btn) btn.disabled = false;
  }
}


// ─────────────────────────────────────────────
//  Smooth scroll for sidebar nav links
// ─────────────────────────────────────────────
document.querySelectorAll(".sidebar-nav .nav-link").forEach((link) => {
  link.addEventListener("click", (e) => {
    // Remove active from all, add to clicked
    document.querySelectorAll(".sidebar-nav .nav-link").forEach((l) =>
      l.classList.remove("active")
    );
    link.classList.add("active");

    // Close sidebar on mobile after nav click
    document.getElementById("sidebar").classList.remove("open");
  });
});
