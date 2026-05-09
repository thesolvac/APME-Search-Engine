/**
 * APME API client — thin wrapper around fetch().
 * Reads/writes JWT from localStorage. Redirects to /login on 401.
 */
const API = (() => {
  const BASE = '/api';

  function token() { return localStorage.getItem('apme_token'); }

  function authHeader() {
    const t = token();
    return t ? { 'Authorization': `Bearer ${t}` } : {};
  }

  async function request(method, path, body = null, isForm = false) {
    const opts = { method, headers: { ...authHeader() } };

    if (body !== null && !isForm) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    } else if (body !== null && isForm) {
      opts.body = body;   // FormData — browser sets Content-Type with boundary
    }

    let res;
    try {
      res = await fetch(BASE + path, opts);
    } catch (err) {
      throw new Error('Network error: ' + err.message);
    }

    if (res.status === 401) {
      localStorage.removeItem('apme_token');
      localStorage.removeItem('apme_user');
      window.location.href = '/login';
      return null;
    }

    return res.json();
  }

  return {
    token,
    get:      (path)        => request('GET',    path),
    post:     (path, body)  => request('POST',   path, body),
    put:      (path, body)  => request('PUT',    path, body),
    del:      (path)        => request('DELETE', path),
    postForm: (path, fd)    => request('POST',   path, fd, true),

    // Auth helpers
    user() {
      try { return JSON.parse(localStorage.getItem('apme_user') || 'null'); }
      catch { return null; }
    },
    setSession(token, user) {
      localStorage.setItem('apme_token', token);
      localStorage.setItem('apme_user', JSON.stringify(user));
    },
    clearSession() {
      localStorage.removeItem('apme_token');
      localStorage.removeItem('apme_user');
    },
    isLoggedIn() { return !!token(); },
    isAdmin()    { return this.user()?.role === 'admin'; },

    // Guard helpers — call at top of each page's init()
    requireAuth() {
      if (!this.isLoggedIn()) { window.location.href = '/login'; return false; }
      return true;
    },
    requireAdmin() {
      if (!this.isLoggedIn()) { window.location.href = '/login'; return false; }
      if (!this.isAdmin())    { window.location.href = '/dashboard'; return false; }
      return true;
    },
    requireGuest() {
      if (this.isLoggedIn()) { window.location.href = '/dashboard'; return false; }
      return true;
    },
  };
})();

// ── Global toast notification ─────────────────────────────────────────────────
function showToast(msg, type = 'info', dur = 3500) {
  const colours = {
    info:    'border-cyan-500  text-cyan-300',
    success: 'border-green-500 text-green-300',
    error:   'border-red-500   text-red-300',
    warn:    'border-yellow-500 text-yellow-300',
  };
  const wrap = document.getElementById('toast-wrap');
  if (!wrap) return;

  const el = document.createElement('div');
  el.className = `toast-item flex items-start gap-3 px-4 py-3 rounded-lg border bg-[#1a1a35]/90 backdrop-blur
                  shadow-2xl text-sm pointer-events-auto ${colours[type] || colours.info}`;
  el.innerHTML = `<span class="mt-px">${{info:'ℹ',success:'✓',error:'✕',warn:'⚠'}[type]??'ℹ'}</span>
                  <span>${msg}</span>`;
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
  }, dur);
}

// ── Format helpers ────────────────────────────────────────────────────────────
function fmtMs(ms) {
  if (ms === undefined || ms === null) return '—';
  return ms < 1 ? `${(ms * 1000).toFixed(0)} µs`
       : ms < 1000 ? `${ms.toFixed(2)} ms`
       : `${(ms / 1000).toFixed(2)} s`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function relTime(iso) {
  const d = new Date(iso), now = Date.now();
  const s = Math.round((now - d) / 1000);
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.round(s/60)}m ago`;
  if (s < 86400)return `${Math.round(s/3600)}h ago`;
  return d.toLocaleDateString();
}
