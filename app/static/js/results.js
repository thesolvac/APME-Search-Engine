if (!API.requireAuth()) throw 0;

const ALG_COLOURS = {
  'KMP':'#00d4ff','Boyer-Moore':'#8b5cf6','Rabin-Karp':'#ffd166',
  'Shift-Or':'#10d98a','Aho-Corasick':'#ff9a3c','AUTO':'#ff4d6d',
};
const NER_COLOURS = {
  DATE:'#00d4ff',TIME:'#10d98a',EMAIL:'#8b5cf6',PHONE:'#ff9a3c',
  IP_ADDRESS:'#ffd166',URL:'#c084fc',HASHTAG:'#fb7185',MENTION:'#34d399',
  ENGLISH_NAME:'#60a5fa',HEBREW_NAME:'#a78bfa',ISRAELI_ID:'#f97316',
};

const result  = JSON.parse(sessionStorage.getItem('apme_result')  || 'null');
const srcText = sessionStorage.getItem('apme_search_text')    || '';
const pattern = sessionStorage.getItem('apme_search_pattern') || '';
const mode    = sessionStorage.getItem('apme_search_mode')    || 'text';

let matchEls   = [];
let currentIdx = -1;

if (!result) {
  document.getElementById('text-viewer').innerHTML =
    '<span class="text-danger">No result found. <a href="/search" class="text-cyan">Go back to search.</a></span>';
}

// ── Summary ribbon ────────────────────────────────────────────────────────────
function populateSummary() {
  if (!result) return;
  const isMulti = mode === 'multi';

  const countEl = document.getElementById('r-count');
  if (isMulti) {
    const total = Object.values(result.results || {})
                        .reduce((s, r) => s + (r.match_count || 0), 0);
    countEl.textContent = total.toLocaleString() + ' total';
  } else {
    countEl.textContent = (result.match_count || 0).toLocaleString();
  }

  const algEl = document.getElementById('r-alg');
  const alg   = result.algorithm || '—';
  algEl.textContent = alg;
  algEl.style.color = ALG_COLOURS[alg] || '#9090bb';

  document.getElementById('r-dur').textContent  = fmtMs(result.duration_ms);
  document.getElementById('r-size').textContent =
    result.text_length
      ? ((result.text_length / 1024).toFixed(1) + ' KB')
      : (result.file_size_bytes
          ? ((result.file_size_bytes / 1024).toFixed(1) + ' KB')
          : '—');
}

// ── Text viewer with highlights ───────────────────────────────────────────────
function buildHighlight(text, pat) {
  if (!pat) return escHtml(text);
  const parts = text.split(pat);
  return parts.map(escHtml).join(
    `<mark class="match-highlight">${escHtml(pat)}</mark>`
  );
}

function populateViewer() {
  const viewer   = document.getElementById('text-viewer');
  const posList  = document.getElementById('positions-list');
  const counter  = document.getElementById('match-counter');

  if (mode === 'multi' && result) {
    // Show a table of patterns → counts
    const rows = Object.entries(result.results || {});
    viewer.innerHTML = rows.map(([pat, r]) =>
      `<div class="flex justify-between py-1 border-b border-[#2e2e50] last:border-0">
        <span class="font-mono text-cyan">${escHtml(pat)}</span>
        <span class="text-t1">${(r.match_count||0).toLocaleString()} match${r.match_count!==1?'es':''}</span>
       </div>`
    ).join('');
    counter.textContent = '';
    posList.innerHTML   = '';
    document.getElementById('nav-controls').classList.add('hidden');
    return;
  }

  if (!srcText) {
    // File mode — no text available for inline highlight
    viewer.innerHTML = `<span class="text-t3">Inline highlighting is available for text searches.<br>
      File: <span class="text-cyan font-mono">${escHtml(result?.file_name || '')}</span></span>`;
    const matches = result?.matches || [];
    posList.innerHTML = matches.slice(0, 200).map((p, i) =>
      `<span class="pos-badge" onclick="scrollToPos(${i})" title="byte offset ${p}">@${p}</span>`
    ).join('');
    counter.textContent = `${matches.length} match${matches.length!==1?'es':''}`;
    document.getElementById('nav-controls').classList.add('hidden');
    return;
  }

  // Text mode — render with highlights
  viewer.innerHTML = buildHighlight(srcText, pattern);
  matchEls = Array.from(viewer.querySelectorAll('.match-highlight'));

  if (matchEls.length) {
    currentIdx = 0;
    highlightCurrent();
  }
  counter.textContent = matchEls.length > 0 ? `1 / ${matchEls.length}` : '0 matches';

  // Position badges
  const matches = result?.matches || [];
  posList.innerHTML = matches.slice(0, 200).map((p, i) =>
    `<span class="pos-badge" onclick="jumpToMatch(${i})" title="byte offset">@${p}</span>`
  ).join('') + (matches.length > 200
    ? `<span class="text-t3 text-xs self-center">…+${matches.length - 200} more</span>` : '');
}

function highlightCurrent() {
  matchEls.forEach((el, i) => el.classList.toggle('current', i === currentIdx));
  if (matchEls[currentIdx]) {
    matchEls[currentIdx].scrollIntoView({ behavior:'smooth', block:'center' });
  }
  document.getElementById('match-counter').textContent =
    `${currentIdx + 1} / ${matchEls.length}`;
}

function nextMatch() {
  if (!matchEls.length) return;
  currentIdx = (currentIdx + 1) % matchEls.length;
  highlightCurrent();
}
function prevMatch() {
  if (!matchEls.length) return;
  currentIdx = (currentIdx - 1 + matchEls.length) % matchEls.length;
  highlightCurrent();
}
function jumpToMatch(i) {
  currentIdx = Math.min(i, matchEls.length - 1);
  highlightCurrent();
}

// ── NER panel ─────────────────────────────────────────────────────────────────
function populateNER() {
  const panel = document.getElementById('ner-panel');
  const enriched = result?.enriched;
  if (!enriched || !enriched.length) {
    panel.innerHTML = '<span class="text-t3 text-sm">No enriched entities found.</span>';
    return;
  }

  // Collect all unique entities across all enriched snippets
  const seen = new Set();
  const entities = [];
  enriched.forEach(e => {
    (e.entities || []).forEach(ent => {
      const key = ent.type + ':' + ent.value;
      if (!seen.has(key)) { seen.add(key); entities.push(ent); }
    });
  });

  if (!entities.length) {
    panel.innerHTML = '<span class="text-t3 text-sm">No named entities detected.</span>';
    return;
  }

  // Group by type
  const byType = {};
  entities.forEach(e => { (byType[e.type] = byType[e.type] || []).push(e.value); });

  panel.innerHTML = Object.entries(byType).map(([type, vals]) => {
    const col = NER_COLOURS[type] || '#9090bb';
    return `
      <div>
        <div class="text-xs text-t3 mb-1.5 uppercase tracking-wider">${escHtml(type)}</div>
        <div class="flex flex-wrap gap-1.5">
          ${vals.map(v => `
            <span class="ner-chip" style="color:${col};border-color:${col}44;background:${col}11">
              ${escHtml(v)}
            </span>`).join('')}
        </div>
      </div>`;
  }).join('');
}

// ── Comparative chart ─────────────────────────────────────────────────────────
async function loadComparison() {
  if (!srcText || !pattern || mode === 'multi' || mode === 'file') {
    document.getElementById('cmp-chart').innerHTML =
      '<span class="text-t3 text-sm">Comparison available for text searches only.</span>';
    document.getElementById('cmp-status').textContent = '';
    return;
  }

  const res = await API.post('/search/compare', { text: srcText, pattern });
  const statusEl = document.getElementById('cmp-status');

  if (!res || res.status === 'error') {
    statusEl.textContent = 'Comparison unavailable.';
    document.getElementById('cmp-chart').innerHTML =
      '<span class="text-t3 text-sm">Could not run comparison.</span>';
    return;
  }

  const { comparison, auto_selected, fastest } = res.data;
  statusEl.textContent = `AUTO selected: ${auto_selected} · Fastest: ${fastest}`;

  const entries = Object.entries(comparison).sort((a,b) => a[1].duration_ms - b[1].duration_ms);
  const maxMs   = Math.max(...entries.map(([,v]) => v.duration_ms), 0.001);
  const autoAlg = result?.algorithm;

  const chart = document.getElementById('cmp-chart');
  chart.innerHTML = entries.map(([name, stats]) => {
    const pct      = Math.round(stats.duration_ms / maxMs * 100);
    const col      = ALG_COLOURS[name] || '#9090bb';
    const isUsed   = name === autoAlg;
    const isFastest= name === fastest;
    const isAuto   = name === auto_selected;
    const badges   = [
      isUsed    ? `<span class="badge bg-cyan/10 text-cyan border border-cyan/30">USED</span>` : '',
      isFastest ? `<span class="badge bg-emerald/10 text-emerald border border-emerald/30">FASTEST ⚡</span>` : '',
      isAuto    ? `<span class="badge bg-purple/10 text-purple border border-purple/30">AUTO</span>` : '',
    ].filter(Boolean).join('');

    return `
      <div class="p-3 rounded-lg ${isUsed ? 'border border-cyan/30 bg-cyan/5' : ''}">
        <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
          <div class="flex items-center gap-2">
            <span class="font-mono text-sm font-bold" style="color:${col}">${escHtml(name)}</span>
            ${badges}
          </div>
          <span class="font-mono text-sm text-t1">${fmtMs(stats.duration_ms)}
            <span class="text-t3 text-xs">(${stats.match_count} match${stats.match_count!==1?'es':''})</span>
          </span>
        </div>
        <div class="bg-bg3 rounded h-3 overflow-hidden">
          <div class="bar-cmp" style="width:0%;background:${col}" data-w="${pct}%"></div>
        </div>
      </div>`;
  }).join('');

  requestAnimationFrame(() => {
    chart.querySelectorAll('.bar-cmp').forEach(b => b.style.width = b.dataset.w);
  });
}

// ── Export ────────────────────────────────────────────────────────────────────
function exportResults() {
  if (!result) return;
  const blob = new Blob([JSON.stringify({ result, pattern, mode }, null, 2)],
                        { type: 'application/json' });
  const a = Object.assign(document.createElement('a'),
    { href: URL.createObjectURL(blob), download: 'apme_results.json' });
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
populateSummary();
populateViewer();
populateNER();
loadComparison();
