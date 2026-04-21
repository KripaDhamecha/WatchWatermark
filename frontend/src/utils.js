const API = 'http://localhost:5000';

const Auth = {
  getToken:  () => localStorage.getItem('ww_token'),
  getUser:   () => { try { return JSON.parse(localStorage.getItem('ww_user')); } catch { return null; } },
  setSession:(token, user) => { localStorage.setItem('ww_token', token); localStorage.setItem('ww_user', JSON.stringify(user)); },
  clear:     () => { localStorage.removeItem('ww_token'); localStorage.removeItem('ww_user'); },
  isLoggedIn:() => !!localStorage.getItem('ww_token'),
  requireAuth: () => { if (!localStorage.getItem('ww_token')) { window.location.href = '/pages/login.html'; return false; } return true; },
  requireGuest:() => { if (localStorage.getItem('ww_token')) { window.location.href = '/pages/dashboard.html'; return false; } return true; }
};

async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const headers = { ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (!(options.body instanceof FormData)) headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  const res  = await fetch(API + path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { Auth.clear(); window.location.href = '/pages/login.html'; throw new Error('Session expired'); }
  if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

function toast(msg, type = 'ok', ms = 3500) {
  let el = document.getElementById('toast');
  if (!el) { el = document.createElement('div'); el.id = 'toast'; document.body.appendChild(el); }
  el.className = `toast toast-${type} show`;
  el.textContent = msg;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

function logout() { Auth.clear(); window.location.href = '/pages/login.html'; }

function initSidebar() {
  const u = Auth.getUser();
  if (!u) return;
  const av = document.getElementById('sideAvatar');
  const nm = document.getElementById('sideUsername');
  const pl = document.getElementById('sidePlan');
  if (av) {
    if (u.avatar) { av.style.backgroundImage = `url('${u.avatar}')`; av.style.backgroundSize='cover'; av.textContent=''; }
    else av.textContent = (u.username||'?')[0].toUpperCase();
  }
  if (nm) nm.textContent = u.username || '';
  if (pl) pl.textContent = u.plan || 'unlimited';
}
