if (!API.requireAdmin()) throw 0;

const ALG_COLOURS = {
  'KMP':'#00d4ff','Boyer-Moore':'#8b5cf6','Rabin-Karp':'#ffd166',
  'Shift-Or':'#10d98a','Aho-Corasick':'#ff9a3c','AUTO':'#ff4d6d',
};
function algColour(n) { return ALG_COLOURS[n] || '#9090bb'; }

// ── Tab navigation ────────────────────────────────────────────────────────────
function showTab(tab) {
  ['users','history','perf'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== tab);
  });
  document.querySelectorAll('.tab-nav-btn').forEach((btn, i) => {
    const tabs = ['users','history','perf'];
    btn.classList.toggle('active',   tabs[i] === tab);
    btn.classList.toggle('text-t2',  tabs[i] !== tab);
    btn.style.color = tabs[i] === tab ? '' : '';
  });
  if (tab === 'history') loadHistory();
  if (tab === 'perf')    { loadGlobalBreakdown(); loadPerfLogs(); }
}

// ── Admin overview stats ──────────────────────────────────────────────────────
async function loadAdminStats() {
  const [usersRes, breakdownRes] = await Promise.all([
    API.get('/admin/users?limit=1'),
    API.get('/stats/algorithms?scope=global'),
  ]);

  function set(id, val, col) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('skeleton');
    el.textContent = val;
    if (col) el.style.color = col;
  }

  if (usersRes?.status === 'success') {
    set('a-users', (usersRes.data?.total || 0).toLocaleString());
  }

  const breakdown = breakdownRes?.data || [];
  const totalSearches = breakdown.reduce((s, e) => s + e.count, 0);
  const avgDur = breakdown.reduce((s, e) => s + e.avg_duration_ms * e.count, 0) / (totalSearches || 1);
  const topAlg = breakdown[0];

  set('a-searches', totalSearches.toLocaleString());
  set('a-avg',      fmtMs(avgDur));
  if (topAlg) set('a-top-alg', topAlg.algorithm, algColour(topAlg.algorithm));
  else         set('a-top-alg', '—');
}

// ── Users table ───────────────────────────────────────────────────────────────
async function loadUsers() {
  const res = await API.get('/admin/users?limit=100');
  const body = document.getElementById('users-body');
  if (!res || res.status === 'error') {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-6">Failed to load users.</td></tr>';
    return;
  }
  const users = res.data?.users || [];
  if (!users.length) {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-t3 py-6">No users found.</td></tr>';
    return;
  }
  body.innerHTML = users.map(u => `
    <tr>
      <td class="font-mono text-t1 font-semibold">${escHtml(u.username)}</td>
      <td class="text-t2">${escHtml(u.email)}</td>
      <td><span class="badge border font-mono role-${u.role}">${u.role}</span></td>
      <td class="status-${u.is_active ? 'on' : 'off'} font-semibold text-xs">
        ${u.is_active ? '● Active' : '○ Disabled'}
      </td>
      <td class="text-t3">${u.created_at ? relTime(u.created_at) : '—'}</td>
      <td class="flex gap-2">
        <button onclick='openEditModal(${JSON.stringify(u)})'
                class="btn-ghost px-2 py-1 text-xs">Edit</button>
        <button onclick="deleteUser('${u.id}','${escHtml(u.username)}')"
                class="px-2 py-1 text-xs rounded-lg border border-red-500/30
                       text-red-400 hover:bg-red-500/10 transition">Del</button>
      </td>
    </tr>`).join('');
}

// ── Search history table ──────────────────────────────────────────────────────
async function loadHistory() {
  const res = await API.get('/admin/search-history?limit=50');
  const body = document.getElementById('history-body');
  if (!res || res.status === 'error') {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-6">Unavailable.</td></tr>';
    return;
  }
  const rows = res.data?.records || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-t3 py-6">No history yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr>
      <td class="font-mono text-xs text-t3">${escHtml(r.user_id || '—')}</td>
      <td class="font-mono text-cyan max-w-[160px] truncate">${escHtml(r.query)}</td>
      <td><span class="badge border font-mono text-xs"
                style="color:${algColour(r.algorithm)};border-color:${algColour(r.algorithm)}44">
            ${escHtml(r.algorithm)}</span></td>
      <td class="text-t1">${(r.matches_count || 0).toLocaleString()}</td>
      <td class="font-mono text-t1">${fmtMs(r.duration_ms)}</td>
      <td class="text-t3">${r.run_at ? relTime(r.run_at) : '—'}</td>
    </tr>`).join('');
}

// ── Performance logs ──────────────────────────────────────────────────────────
async function loadGlobalBreakdown() {
  const res = await API.get('/stats/algorithms?scope=global');
  const wrap = document.getElementById('global-breakdown');
  if (!res || !res.data?.length) {
    wrap.innerHTML = '<span class="text-t3 text-sm">No performance data yet.</span>';
    return;
  }
  const maxMs = Math.max(...res.data.map(e => e.avg_duration_ms), 0.001);
  wrap.innerHTML = res.data.map(e => {
    const pct = Math.round(e.avg_duration_ms / maxMs * 100);
    const col = algColour(e.algorithm);
    return `
      <div>
        <div class="flex justify-between text-xs mb-1">
          <span class="font-mono font-semibold" style="color:${col}">${escHtml(e.algorithm)}</span>
          <span class="text-t3">${e.count} runs · avg ${fmtMs(e.avg_duration_ms)}</span>
        </div>
        <div class="bg-bg3 rounded h-2 overflow-hidden">
          <div style="width:0%;height:100%;background:${col};border-radius:4px;
                      transition:width 1s cubic-bezier(.4,0,.2,1)" data-w="${pct}%"></div>
        </div>
      </div>`;
  }).join('');
  requestAnimationFrame(() => {
    wrap.querySelectorAll('[data-w]').forEach(b => b.style.width = b.dataset.w);
  });
}

async function loadPerfLogs() {
  const alg = document.getElementById('alg-filter').value;
  const path = alg
    ? `/admin/performance-logs?algorithm=${encodeURIComponent(alg)}&limit=50`
    : '/admin/performance-logs?limit=50';
  const res  = await API.get(path);
  const body = document.getElementById('perf-body');
  if (!res || res.status === 'error') {
    body.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-6">Unavailable.</td></tr>';
    return;
  }
  const rows = res.data?.logs || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-center text-t3 py-6">No logs yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr>
      <td><span class="badge border font-mono"
               style="color:${algColour(r.algorithm)};border-color:${algColour(r.algorithm)}44">
            ${escHtml(r.algorithm)}</span></td>
      <td class="font-mono text-xs text-t3 max-w-[140px] truncate">${escHtml(r.file_path || '—')}</td>
      <td class="font-mono text-xs">${r.text_size_bytes ? (r.text_size_bytes/1024).toFixed(1)+' KB' : '—'}</td>
      <td class="font-mono text-t1">${fmtMs(r.duration_ms)}</td>
      <td class="text-t1">${(r.matches_count||0).toLocaleString()}</td>
      <td class="font-mono text-xs text-t3">${escHtml(r.user_id || '—')}</td>
      <td class="text-t3">${r.created_at ? relTime(r.created_at) : '—'}</td>
    </tr>`).join('');
}

// ── Modal helpers ─────────────────────────────────────────────────────────────
function openCreateModal() {
  document.getElementById('modal-title').textContent   = 'New User';
  document.getElementById('modal-user-id').value       = '';
  document.getElementById('m-username').value          = '';
  document.getElementById('m-email').value             = '';
  document.getElementById('m-pass').value              = '';
  document.getElementById('m-role').value              = 'user';
  document.getElementById('m-active').checked          = true;
  document.getElementById('m-pass-row').classList.remove('hidden');
  document.getElementById('modal-err').classList.add('hidden');
  document.getElementById('user-modal').classList.remove('hidden');
}

function openEditModal(u) {
  document.getElementById('modal-title').textContent   = 'Edit User';
  document.getElementById('modal-user-id').value       = u.id;
  document.getElementById('m-username').value          = u.username;
  document.getElementById('m-email').value             = u.email;
  document.getElementById('m-pass').value              = '';
  document.getElementById('m-role').value              = u.role;
  document.getElementById('m-active').checked          = u.is_active;
  document.getElementById('m-pass-row').classList.remove('hidden');
  document.getElementById('modal-err').classList.add('hidden');
  document.getElementById('user-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('user-modal').classList.add('hidden');
}

async function submitUserForm(e) {
  e.preventDefault();
  const errEl = document.getElementById('modal-err');
  errEl.classList.add('hidden');

  const id       = document.getElementById('modal-user-id').value;
  const username = document.getElementById('m-username').value.trim();
  const email    = document.getElementById('m-email').value.trim();
  const pass     = document.getElementById('m-pass').value;
  const role     = document.getElementById('m-role').value;
  const isActive = document.getElementById('m-active').checked;

  const btn = document.getElementById('modal-submit-btn');
  btn.disabled = true; btn.textContent = 'Saving…';

  try {
    let res;
    if (id) {
      const body = { username, email, role, is_active: isActive };
      if (pass) body.password = pass;
      res = await API.put(`/admin/users/${id}`, body);
    } else {
      res = await API.post('/admin/users', { username, email, password: pass, role });
    }
    if (!res || res.status === 'error') {
      errEl.textContent = res?.message || 'Save failed.';
      errEl.classList.remove('hidden');
      return;
    }
    showToast(id ? 'User updated.' : 'User created.', 'success');
    closeModal();
    loadUsers();
  } finally {
    btn.disabled = false; btn.textContent = 'Save';
  }
}

async function deleteUser(id, name) {
  if (!confirm(`Delete user "${name}"? This cannot be undone.`)) return;
  const res = await API.del(`/admin/users/${id}`);
  if (!res || res.status === 'error') {
    showToast(res?.message || 'Delete failed.', 'error'); return;
  }
  showToast(`User "${name}" deleted.`, 'success');
  loadUsers();
}

// Close modal on backdrop click
document.getElementById('user-modal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});

// ── Boot ──────────────────────────────────────────────────────────────────────
loadAdminStats();
loadUsers();
