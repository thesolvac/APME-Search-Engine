if (!API.requireAuth()) throw 0;

let currentMode = 'text';
let selectedAlg = 'AUTO';
let acTimer = null;
let selectedFile = null;

// ── Prefill from trending click ───────────────────────────────────────────────
const prefill = sessionStorage.getItem('apme_prefill');
if (prefill) {
  sessionStorage.removeItem('apme_prefill');
  document.getElementById('pattern-input').value = prefill;
}

// ── Mode switching ─────────────────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  ['text','file','multi'].forEach(m => {
    document.getElementById('panel-' + m).classList.toggle('hidden', m !== mode);
    document.getElementById('mode-' + m).classList.toggle('active', m === mode);
  });
  document.getElementById('pattern-row').classList.toggle('hidden', mode === 'multi');
}

// ── Algorithm pill selection ──────────────────────────────────────────────────
function setAlg(btn) {
  document.querySelectorAll('.alg-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  selectedAlg = btn.dataset.alg;
}

// ── File drag-and-drop ────────────────────────────────────────────────────────
function onDragOver(e)  { e.preventDefault(); document.getElementById('dropzone').classList.add('drag-over'); }
function onDragLeave()  { document.getElementById('dropzone').classList.remove('drag-over'); }
function onDrop(e) {
  e.preventDefault();
  document.getElementById('dropzone').classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) applyFile(f);
}
function onFileChange(e) { if (e.target.files[0]) applyFile(e.target.files[0]); }
function applyFile(f) {
  selectedFile = f;
  document.getElementById('drop-placeholder').classList.add('hidden');
  document.getElementById('drop-selected').classList.remove('hidden');
  document.getElementById('drop-filename').textContent = f.name;
  document.getElementById('drop-filesize').textContent =
    (f.size / 1024).toFixed(1) + ' KB';
}

// ── Autocomplete ──────────────────────────────────────────────────────────────
function onPatternInput(val) {
  clearTimeout(acTimer);
  const dd = document.getElementById('ac-dropdown');
  if (!val || val.length < 2) { dd.classList.add('hidden'); return; }
  acTimer = setTimeout(async () => {
    const res = await API.get(`/search/autocomplete?q=${encodeURIComponent(val)}&scope=global`);
    if (!res || !res.data?.length) { dd.classList.add('hidden'); return; }
    dd.innerHTML = res.data.map(s =>
      `<div class="ac-item" onclick="selectAC('${escHtml(s)}')">${escHtml(s)}</div>`
    ).join('');
    dd.classList.remove('hidden');
  }, 260);
}
function selectAC(val) {
  document.getElementById('pattern-input').value = val;
  document.getElementById('ac-dropdown').classList.add('hidden');
}
document.addEventListener('click', e => {
  if (!e.target.closest('#pattern-row'))
    document.getElementById('ac-dropdown').classList.add('hidden');
});

// ── Trending row ──────────────────────────────────────────────────────────────
async function loadTrending() {
  const res = await API.get('/stats/trending?limit=8&days=7');
  const row = document.getElementById('trending-row');
  if (!res || !res.data?.length) {
    row.innerHTML = '<span class="text-t3 text-xs">No trending searches yet.</span>';
    return;
  }
  row.innerHTML = res.data.map(({query, count}) => `
    <button class="trend-chip" onclick="useTrend('${escHtml(query)}')">
      ${escHtml(query)}
      <span class="text-t3 text-xs">${count}</span>
    </button>`).join('');
}
function useTrend(q) {
  document.getElementById('pattern-input').value = q;
  document.getElementById('pattern-input').focus();
}

// ── Search ────────────────────────────────────────────────────────────────────
async function doSearch() {
  const btn   = document.getElementById('search-btn');
  const fuzzy = document.getElementById('fuzzy-toggle').checked;

  // Collect inputs based on mode
  let payload, endpoint, isForm = false;

  if (currentMode === 'text') {
    const text    = document.getElementById('text-input').value.trim();
    const pattern = document.getElementById('pattern-input').value.trim();
    if (!text)    { showToast('Enter text to search.', 'warn'); return; }
    if (!pattern) { showToast('Enter a search pattern.', 'warn'); return; }
    endpoint = '/search/text';
    payload  = { text, pattern, algorithm: selectedAlg, fuzzy, enrich: true };

  } else if (currentMode === 'file') {
    const pattern = document.getElementById('pattern-input').value.trim();
    if (!selectedFile) { showToast('Please select a file.', 'warn'); return; }
    if (!pattern)      { showToast('Enter a search pattern.', 'warn'); return; }
    endpoint = '/search/file';
    const fd = new FormData();
    fd.append('file', selectedFile);
    fd.append('pattern', pattern);
    fd.append('algorithm', selectedAlg);
    fd.append('fuzzy', fuzzy ? 'true' : 'false');
    payload  = fd;
    isForm   = true;

  } else {  // multi
    const text     = document.getElementById('text-input-multi').value.trim();
    const rawPats  = document.getElementById('multi-patterns').value.trim();
    const patterns = rawPats.split('\n').map(s => s.trim()).filter(Boolean);
    if (!text)            { showToast('Enter text to search.', 'warn'); return; }
    if (!patterns.length) { showToast('Enter at least one pattern.', 'warn'); return; }
    endpoint = '/search/multi';
    payload  = { text, patterns };
  }

  btn.disabled = true;
  btn.innerHTML = `<svg class="animate-spin w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
  </svg>Searching…`;

  try {
    let res;
    if (isForm) res = await API.postForm(endpoint, payload);
    else        res = await API.post(endpoint, payload);

    if (!res || res.status === 'error') {
      showToast(res?.message || 'Search failed.', 'error');
      return;
    }

    // Persist result for the results page
    sessionStorage.setItem('apme_result', JSON.stringify(res.data));
    if (currentMode === 'text') {
      sessionStorage.setItem('apme_search_text',    document.getElementById('text-input').value);
      sessionStorage.setItem('apme_search_pattern', document.getElementById('pattern-input').value);
    } else if (currentMode === 'multi') {
      sessionStorage.setItem('apme_search_text',    document.getElementById('text-input-multi').value);
      sessionStorage.setItem('apme_search_pattern', '');
    } else {
      sessionStorage.removeItem('apme_search_text');
      sessionStorage.setItem('apme_search_pattern', document.getElementById('pattern-input').value);
    }
    sessionStorage.setItem('apme_search_mode', currentMode);
    window.location.href = '/results';

  } catch (err) {
    showToast('Network error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/>
    </svg>Search`;
  }
}

// ── Enter key shortcut ────────────────────────────────────────────────────────
document.getElementById('pattern-input')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch();
});

loadTrending();
