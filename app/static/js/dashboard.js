if (!API.requireAuth()) throw 0;

const user = API.user();
if (user) {
  document.getElementById('welcome-msg').textContent =
    'Welcome back, ' + (user.username || user.email);
}

const ALG_COLOURS = {
  'KMP':'#00d4ff','Boyer-Moore':'#8b5cf6','Rabin-Karp':'#ffd166',
  'Shift-Or':'#10d98a','Aho-Corasick':'#ff9a3c','AUTO':'#ff4d6d','Fuzzy':'#c084fc',
};

function algColour(name) { return ALG_COLOURS[name] || '#9090bb'; }

// ── Stat cards ────────────────────────────────────────────────────────────────
async function loadStats() {
  const res = await API.get('/stats/me');
  if (!res || res.status === 'error') return;
  const d = res.data;

  function set(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('skeleton');
    el.textContent = val;
  }
  set('s-total',   d.total_searches?.toLocaleString() ?? '0');
  set('s-matches', d.total_matches?.toLocaleString()  ?? '0');
  set('s-avg-ms',  fmtMs(d.avg_duration_ms));
  const topEl = document.getElementById('s-top-alg');
  if (topEl) {
    topEl.classList.remove('skeleton');
    topEl.textContent = d.most_used_algorithm || '—';
    topEl.style.color = algColour(d.most_used_algorithm);
  }

  // Algorithm breakdown chart
  const algs = Object.entries(d.algorithms || {}).sort((a,b) => b[1]-a[1]);
  const total = algs.reduce((s,[,v]) => s+v, 0) || 1;
  const chart = document.getElementById('alg-chart');
  chart.innerHTML = algs.length ? algs.map(([name, count]) => {
    const pct = Math.round(count / total * 100);
    const col = algColour(name);
    return `
      <div>
        <div class="flex justify-between text-xs mb-1">
          <span style="color:${col}" class="font-mono font-semibold">${escHtml(name)}</span>
          <span class="text-t3">${count} <span class="text-t3/60">(${pct}%)</span></span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:0%;background:${col}" data-w="${pct}%"></div>
        </div>
      </div>`;
  }).join('') : '<p class="text-t3 text-sm">No searches yet.</p>';

  requestAnimationFrame(() => {
    chart.querySelectorAll('.bar-fill').forEach(b => b.style.width = b.dataset.w);
  });
}

// ── Recommendations ───────────────────────────────────────────────────────────
async function loadRecommendations() {
  const res = await API.get('/stats/recommendations');
  if (!res || res.status === 'error') return;
  const d = res.data;

  const algEl = document.getElementById('rec-alg');
  algEl.classList.remove('skeleton');
  algEl.textContent   = d.recommended_algorithm || 'AUTO';
  algEl.style.color   = algColour(d.recommended_algorithm);

  const confEl = document.getElementById('rec-confidence');
  confEl.textContent = (d.confidence || 'none').toUpperCase();

  const tipsEl = document.getElementById('rec-tips');
  tipsEl.innerHTML = (d.tips || []).map(t =>
    `<div class="rec-item p-3 text-xs text-t2">${escHtml(t)}</div>`
  ).join('') || '';

  const insEl = document.getElementById('rec-insights');
  insEl.innerHTML = (d.insights || []).map(ins =>
    `<div class="rec-item rec-insight p-3 text-xs text-purple">${escHtml(ins)}</div>`
  ).join('') || '';
}

// ── Trending ──────────────────────────────────────────────────────────────────
async function loadTrending() {
  const res = await API.get('/stats/trending?limit=10&days=7');
  if (!res || res.status === 'error') return;
  const list = document.getElementById('trending-list');
  list.innerHTML = res.data.length
    ? res.data.map(({query, count}) => `
        <a href="/search" onclick="sessionStorage.setItem('apme_prefill','${escHtml(query)}')"
           class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs
                  bg-bg3 border border-[#2e2e50] text-t2 hover:border-cyan hover:text-cyan transition">
          ${escHtml(query)}
          <span class="text-t3">${count}</span>
        </a>`).join('')
    : '<span class="text-t3 text-sm">No trending data yet.</span>';
}

// ── Recent history ────────────────────────────────────────────────────────────
async function loadHistory() {
  const res  = await API.get('/search/history?limit=20');
  const body = document.getElementById('history-body');
  if (!res || res.status === 'error') {
    body.innerHTML = '<tr><td colspan="5" class="text-center text-t3 py-6">History unavailable.</td></tr>';
    return;
  }
  const rows = (res.data?.records || []).slice(0, 20);
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="text-center text-t3 py-6">No searches yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr>
      <td class="font-mono text-cyan max-w-[160px] truncate">${escHtml(r.query)}</td>
      <td><span class="badge border font-mono" style="color:${algColour(r.algorithm)};
          border-color:${algColour(r.algorithm)}44">${escHtml(r.algorithm)}</span></td>
      <td class="text-t1">${(r.matches_count||0).toLocaleString()}</td>
      <td class="text-t1 font-mono">${fmtMs(r.duration_ms)}</td>
      <td class="text-t3">${relTime(r.run_at)}</td>
    </tr>`).join('');
}

// Boot
Promise.all([loadStats(), loadRecommendations(), loadTrending(), loadHistory()]);
