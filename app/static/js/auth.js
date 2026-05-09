// Redirect if already logged in
API.requireGuest();

// ── Particle background ───────────────────────────────────────────────────────
(function spawnParticles() {
  const wrap = document.getElementById('particles');
  const colours = ['#00d4ff','#8b5cf6','#10d98a','#ffd166'];
  for (let i = 0; i < 22; i++) {
    const p = document.createElement('div');
    const size = 3 + Math.random() * 6;
    p.className = 'particle';
    Object.assign(p.style, {
      width: size + 'px', height: size + 'px',
      left:  Math.random() * 100 + 'vw',
      top:   Math.random() * 100 + 'vh',
      background: colours[Math.floor(Math.random() * colours.length)] + '55',
      animationDuration: (8 + Math.random() * 14) + 's',
      animationDelay:    (-Math.random() * 12) + 's',
    });
    wrap.appendChild(p);
  }
})();

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  const isLogin = tab === 'login';
  document.getElementById('form-login').classList.toggle('hidden', !isLogin);
  document.getElementById('form-register').classList.toggle('hidden',  isLogin);
  document.getElementById('tab-login').classList.toggle('active',  isLogin);
  document.getElementById('tab-register').classList.toggle('active', !isLogin);
  document.getElementById('tab-login').classList.toggle('text-t2',  !isLogin);
  document.getElementById('tab-register').classList.toggle('text-t2', isLogin);
  clearErrors();
}

// ── Error display helpers ─────────────────────────────────────────────────────
function showErr(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}
function clearErrors() {
  document.querySelectorAll('.field-err').forEach(el => {
    el.textContent = '';
    el.classList.add('hidden');
  });
}
function setBusy(btnId, busy, label = 'Sign In') {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.disabled = busy;
  btn.textContent = busy ? 'Please wait…' : label;
  btn.style.opacity = busy ? '0.6' : '';
}

// ── Login ─────────────────────────────────────────────────────────────────────
async function doLogin(e) {
  e.preventDefault();
  clearErrors();

  const email = document.getElementById('login-email').value.trim();
  const pass  = document.getElementById('login-pass').value;
  let valid = true;

  if (!email) { showErr('login-email-err', 'Email is required'); valid = false; }
  if (!pass)  { showErr('login-pass-err',  'Password is required'); valid = false; }
  if (!valid) return;

  setBusy('login-btn', true, 'Sign In');
  try {
    const res = await API.post('/auth/login', { email, password: pass });
    if (!res) return;   // redirected
    if (res.status === 'error') {
      showErr('login-general-err', res.message || 'Login failed');
      return;
    }
    API.setSession(res.data.token, res.data.user);
    showToast('Welcome back, ' + (res.data.user.username || res.data.user.email) + '!', 'success');
    setTimeout(() => window.location.href = '/dashboard', 600);
  } catch (err) {
    showErr('login-general-err', 'Connection error. Try again.');
  } finally {
    setBusy('login-btn', false, 'Sign In');
  }
}

// ── Register ──────────────────────────────────────────────────────────────────
async function doRegister(e) {
  e.preventDefault();
  clearErrors();

  const username = document.getElementById('reg-username').value.trim();
  const email    = document.getElementById('reg-email').value.trim();
  const pass     = document.getElementById('reg-pass').value;
  const pass2    = document.getElementById('reg-pass2').value;
  let valid = true;

  if (!username) { showErr('reg-username-err', 'Username is required'); valid = false; }
  if (!email)    { showErr('reg-email-err',    'Email is required');    valid = false; }
  if (!pass)     { showErr('reg-pass-err',     'Password is required'); valid = false; }
  else if (pass.length < 8) { showErr('reg-pass-err', 'At least 8 characters'); valid = false; }
  if (pass !== pass2) { showErr('reg-pass2-err', 'Passwords do not match'); valid = false; }
  if (!valid) return;

  setBusy('reg-btn', true, 'Create Account');
  try {
    const res = await API.post('/auth/register', { username, email, password: pass });
    if (!res) return;
    if (res.status === 'error') {
      showErr('reg-general-err', res.message || 'Registration failed');
      return;
    }
    showToast('Account created! Please sign in.', 'success');
    switchTab('login');
    document.getElementById('login-email').value = email;
  } catch (err) {
    showErr('reg-general-err', 'Connection error. Try again.');
  } finally {
    setBusy('reg-btn', false, 'Create Account');
  }
}
