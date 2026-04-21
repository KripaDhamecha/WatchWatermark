// =========================================
// WatermarkWatch v2 — Shared Utilities
// =========================================

const API = 'http://localhost:5000';

// ── Token storage ──
const Auth = {
  getToken: () => localStorage.getItem('ww_token'),
  getUser:  () => { try { return JSON.parse(localStorage.getItem('ww_user')); } catch { return null; } },
  setSession: (token, user) => {
    localStorage.setItem('ww_token', token);
    localStorage.setItem('ww_user', JSON.stringify(user));
  },
  clear: () => {
    localStorage.removeItem('ww_token');
    localStorage.removeItem('ww_user');
  },
  isLoggedIn: () => !!localStorage.getItem('ww_token'),
  requireAuth: () => {
    if (!localStorage.getItem('ww_token')) {
      window.location.href = '/pages/login.html';
      return false;
    }
    return true;
  },
  requireGuest: () => {
    if (localStorage.getItem('ww_token')) {
      window.location.href = '/pages/dashboard.html';
      return false;
    }
    return true;
  }
};

// ── API helper ──
async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const headers = { ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  // Don't set Content-Type for FormData (browser sets it with boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  const res = await fetch(API + path, { ...options, headers });
  const data = await res.json().catch(() => ({}));

  if (res.status === 401) {
    Auth.clear();
    window.location.href = '/pages/login.html';
    throw new Error('Session expired');
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ── Toast notifications ──
function toast(msg, type = 'ok', duration = 3500) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.className = `toast-${type} show`;
  el.textContent = msg;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), duration);
}

// ── Render nav user info ──
function renderNav() {
  const user = Auth.getUser();
  if (!user) return;
  const avatarEl = document.getElementById('navAvatar');
  const nameEl   = document.getElementById('navUsername');
  if (avatarEl) avatarEl.textContent = user.username[0].toUpperCase();
  if (nameEl)   nameEl.textContent   = user.username;
}

// ── Logout ──
function logout() {
  Auth.clear();
  window.location.href = '/pages/login.html';
}
