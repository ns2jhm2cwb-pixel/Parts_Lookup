let pageInfo  = null;   // info from content script on current tab
let allModels = {};     // { displayName: materialNumber }
let currentToken = '';

const pageCard  = document.getElementById('pageCard');
const modelName = document.getElementById('modelName');
const matNum    = document.getElementById('matNum');
const nameEdit  = document.getElementById('nameEdit');
const addBtn    = document.getElementById('addBtn');
const buildBtn  = document.getElementById('buildBtn');
const modelList = document.getElementById('modelList');
const emptyMsg  = document.getElementById('emptyMsg');
const statusEl  = document.getElementById('status');
const notPortal = document.getElementById('notPortalMsg');

// ── init ──────────────────────────────────────────────────────────────────────

async function init() {
  const stored = await chrome.storage.local.get(['models', 'token']);
  allModels    = stored.models || {};
  currentToken = stored.token  || '';
  renderModelList();

  // Query the active tab's content script
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && tab.url.includes('ssc.stihl.com')) {
      pageInfo = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_INFO' });
      if (pageInfo && pageInfo.token) {
        currentToken = pageInfo.token;
        await chrome.storage.local.set({ token: currentToken });
      }
      showPageDetected();
    } else {
      showNotOnPortal();
    }
  } catch {
    showNotOnPortal();
  }
}

// ── page card ─────────────────────────────────────────────────────────────────

function showPageDetected() {
  if (!pageInfo) { showNotOnPortal(); return; }

  const name = pageInfo.modelName || '';
  const mn   = pageInfo.materialNumber || '';

  if (!mn) {
    // On portal but no model detected (e.g. home/search page)
    pageCard.className = 'not-portal';
    modelName.textContent = 'No IPL detected on this page';
    matNum.textContent = 'Navigate to a specific model\'s IPL page';
    addBtn.textContent = 'Browse to an IPL page first';
    addBtn.disabled = true;
    nameEdit.style.display = 'none';
    return;
  }

  pageCard.className = 'detected';
  notPortal.style.display = 'none';

  // Check if already saved
  const alreadySaved = Object.values(allModels).includes(mn);

  modelName.textContent = name || mn;
  matNum.textContent = mn;

  nameEdit.style.display = 'block';
  nameEdit.value = name || '';
  nameEdit.placeholder = 'Enter model name (e.g. BR 800 C-E)';

  if (alreadySaved) {
    addBtn.textContent = '✓ Already in your list';
    addBtn.disabled = true;
  } else {
    addBtn.textContent = '+ Add this model';
    addBtn.disabled = false;
  }
}

function showNotOnPortal() {
  pageCard.className = 'not-portal';
  modelName.textContent = 'Not on the Stihl portal';
  matNum.textContent = '';
  nameEdit.style.display = 'none';
  addBtn.textContent = 'Open an IPL page on the Stihl portal';
  addBtn.disabled = true;
  notPortal.style.display = 'block';
}

// ── add model ─────────────────────────────────────────────────────────────────

addBtn.addEventListener('click', async () => {
  const mn   = pageInfo?.materialNumber;
  const name = nameEdit.value.trim() || pageInfo?.modelName || mn;
  if (!mn || !name) return;

  setStatus('Verifying…');
  addBtn.disabled = true;

  chrome.runtime.sendMessage(
    { type: 'VERIFY_MODEL', materialNumber: mn, token: currentToken },
    async (resp) => {
      if (!resp || !resp.ok) {
        setStatus('Could not verify — check your connection or token.', true);
        addBtn.disabled = false;
        return;
      }

      // Use API-returned model name as fallback if user left name blank
      const finalName = name || resp.modelName || mn;
      allModels[finalName] = mn;
      await chrome.storage.local.set({ models: allModels });

      renderModelList();
      addBtn.textContent = '✓ Added!';
      setStatus(`Added ${finalName} (${resp.partCount} parts found)`);
    }
  );
});

// ── model list ────────────────────────────────────────────────────────────────

function renderModelList() {
  const names = Object.keys(allModels);
  buildBtn.disabled = names.length === 0;
  if (names.length === 0) {
    modelList.innerHTML = '<div id="emptyMsg">No models yet</div>';
    return;
  }
  modelList.innerHTML = names.map(n => `
    <div class="model-row">
      <span class="model-row-name" title="${n}">${n}</span>
      <span class="model-row-num">${allModels[n]}</span>
      <button class="remove-btn" data-name="${n}" title="Remove">×</button>
    </div>
  `).join('');

  modelList.querySelectorAll('.remove-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      delete allModels[btn.dataset.name];
      await chrome.storage.local.set({ models: allModels });
      renderModelList();
      setStatus('');
    });
  });
}

// ── build CSV ─────────────────────────────────────────────────────────────────

buildBtn.addEventListener('click', () => {
  if (!currentToken) {
    setStatus('No token — open the Stihl portal first.', true);
    return;
  }
  buildBtn.disabled = true;
  buildBtn.textContent = 'Fetching parts…';
  setStatus('');

  chrome.runtime.sendMessage(
    { type: 'BUILD_MATRIX', models: allModels, token: currentToken },
    (resp) => {
      buildBtn.disabled = false;
      buildBtn.textContent = 'Build & Download CSV';

      if (!resp || !resp.ok) {
        setStatus('Something went wrong. Try refreshing the Stihl portal.', true);
        return;
      }

      // Check for any 401s in progress
      const expired = resp.progress.filter(p => !p.ok && p.error?.includes('401'));
      if (expired.length) {
        setStatus('Token expired — open the Stihl portal and reopen this extension.', true);
        return;
      }

      // Trigger CSV download
      const blob = new Blob([resp.csv], { type: 'text/csv' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;
      a.download = 'stihl_parts_matrix.csv';
      a.click();
      URL.revokeObjectURL(url);

      const ok  = resp.progress.filter(p => p.ok).length;
      const err = resp.progress.filter(p => !p.ok).length;
      setStatus(err ? `Done — ${ok} ok, ${err} failed` : `Done! ${ok} models exported.`);
    }
  );
});

// ── helpers ───────────────────────────────────────────────────────────────────

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.className   = isError ? 'err' : (msg ? 'ok' : '');
}

init();
