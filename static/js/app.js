// ── Theme (dark / light) ───────────────────────────────────────────────────────
const THEME_SUN  = '<circle cx="12" cy="12" r="4.5"/><path d="M12 1.5v2M12 20.5v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1.5 12h2M20.5 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>';
const THEME_MOON = '<path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z"/>';
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const icon = document.getElementById('themeIcon');
  if (icon) icon.innerHTML = (t === 'dark') ? THEME_MOON : THEME_SUN;
  localStorage.setItem('toolboxTheme', t);
}
function toggleTheme() {
  applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}
applyTheme(localStorage.getItem('toolboxTheme') || 'dark');

// Open the Run launcher: pick a toolbox, then a command.
function openLauncher() {
  openModal('launcherModal');
  loadToolboxes();
}

// ── Keyboard activation for role="button" elements ──────────────────────────────
// Toolbox / session rows are divs with role="button"; Enter and Space should
// activate them just like a real button does.
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const el = e.target.closest('[role="button"]');
  if (!el) return;
  // If the key was aimed at a real control nested in the row (e.g. the kill
  // button), let that control handle it instead of activating the whole row.
  if (e.target !== el && e.target.closest('button, a, input, select, textarea')) return;
  e.preventDefault();
  el.click();
});

// ── Modal focus management ──────────────────────────────────────────────────────
// Records the trigger element, moves focus into the dialog on open, restores it on
// close, and traps Tab within the open dialog.
let _modalReturnFocus = null;
const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

function openModal(overlayId, focusId) {
  _modalReturnFocus = document.activeElement;
  const overlay = document.getElementById(overlayId);
  overlay.classList.add('open');
  const target = focusId ? document.getElementById(focusId) : null;
  (target || overlay.querySelector(FOCUSABLE))?.focus();
}
function closeModal(overlayId) {
  document.getElementById(overlayId).classList.remove('open');
  if (_modalReturnFocus && document.contains(_modalReturnFocus)) _modalReturnFocus.focus();
  _modalReturnFocus = null;
}
function openModalEl() { return document.querySelector('.modal-overlay.open .modal'); }

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Tab') return;
  const modal = openModalEl();
  if (!modal) return;
  const items = [...modal.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

// ── Themed confirm / prompt dialog (replaces native confirm()/prompt()) ─────────
// Promise-based: `await uiConfirm({...})` → true/false; `await uiPrompt({...})` →
// string or null. Works while another modal is open (it stacks above).
let _dlgResolve = null, _dlgReturnFocus = null, _dlgIsPrompt = false;

function _openDialog(o) {
  return new Promise(resolve => {
    _dlgResolve = resolve;
    _dlgIsPrompt = !!o.prompt;
    _dlgReturnFocus = document.activeElement;

    document.getElementById('dialogTitle').textContent = o.title || '';
    const msg = document.getElementById('dialogMsg');
    msg.textContent = o.message || '';
    msg.style.display = o.message ? '' : 'none';

    const input = document.getElementById('dialogInput');
    input.style.display = o.prompt ? '' : 'none';
    if (o.prompt) { input.value = o.value || ''; input.placeholder = o.placeholder || ''; }

    document.getElementById('dialogCancel').textContent  = o.cancelText || 'Cancel';
    const confirm = document.getElementById('dialogConfirm');
    confirm.textContent = o.confirmText || 'OK';
    confirm.className = 'dialog-btn confirm' + (o.danger ? ' danger' : '');

    document.getElementById('dialogOverlay').classList.add('open');
    document.addEventListener('keydown', _dlgKey, true);
    if (o.prompt) { input.focus(); input.select(); } else { confirm.focus(); }
  });
}

function uiConfirm(o) { return _openDialog({ ...o, prompt: false }); }
function uiPrompt(o)  { return _openDialog({ ...o, prompt: true  }); }

function _dlgDone(value) {
  document.getElementById('dialogOverlay').classList.remove('open');
  document.removeEventListener('keydown', _dlgKey, true);
  const r = _dlgResolve; _dlgResolve = null;
  if (_dlgReturnFocus && document.contains(_dlgReturnFocus)) { try { _dlgReturnFocus.focus(); } catch (e) {} }
  if (r) r(value);
}
function _dlgConfirm() { _dlgDone(_dlgIsPrompt ? document.getElementById('dialogInput').value : true); }
function _dlgCancel()  { _dlgDone(_dlgIsPrompt ? null : false); }

// ── Themed tooltips (replace native title=) ─────────────────────────────────────
// One shared fixed element positioned to the hovered/focused [data-tip] target.
// position:fixed escapes the modals' overflow clipping; we flip above the target
// near the bottom edge and clamp horizontally to the viewport.
const _tip = document.createElement('div');
_tip.id = 'tooltip';
document.body.appendChild(_tip);
let _tipTimer = null, _tipTarget = null;

function _positionTip(el) {
  const r = el.getBoundingClientRect();
  const t = _tip.getBoundingClientRect();
  const gap = 8, pad = 6;
  let top = r.bottom + gap;
  if (top + t.height > window.innerHeight - pad) top = r.top - gap - t.height; // flip up
  let left = r.left + r.width / 2 - t.width / 2;
  left = Math.max(pad, Math.min(left, window.innerWidth - t.width - pad));      // clamp
  _tip.style.top  = Math.max(pad, top) + 'px';
  _tip.style.left = left + 'px';
}
function _showTip(el) {
  const text = el.getAttribute('data-tip');
  if (!text) return;
  _tipTarget = el;
  _tip.textContent = text;
  _positionTip(el);                 // measure + place with the real text
  _tip.classList.add('show');
}
function _hideTip() { _tip.classList.remove('show'); _tipTarget = null; clearTimeout(_tipTimer); }

document.addEventListener('mouseover', (e) => {
  const el = e.target.closest('[data-tip]');
  if (!el || el === _tipTarget) return;
  clearTimeout(_tipTimer);
  _tipTimer = setTimeout(() => _showTip(el), 350);   // brief delay, like a native tip
});
document.addEventListener('mouseout', (e) => {
  const el = e.target.closest('[data-tip]');
  if (!el) return;
  // Ignore moves that stay inside the same tipped element (e.g. onto its icon).
  if (e.relatedTarget && el.contains(e.relatedTarget)) return;
  _hideTip();
});
document.addEventListener('focusin',  (e) => { const el = e.target.closest('[data-tip]'); if (el) _showTip(el); });
document.addEventListener('focusout', _hideTip);
window.addEventListener('scroll', _hideTip, true);   // don't leave a tip floating mid-scroll

function _dlgKey(e) {
  if (!document.getElementById('dialogOverlay').classList.contains('open')) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); _dlgCancel(); }
  else if (e.key === 'Enter' && document.activeElement?.id !== 'dialogCancel') {
    e.preventDefault(); e.stopPropagation(); _dlgConfirm();
  } else if (e.key === 'Tab') {
    const f = [...document.querySelectorAll('#dialogOverlay button, #dialogOverlay input')]
                .filter(el => el.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); e.stopPropagation(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); e.stopPropagation(); first.focus(); }
  }
}

// ── State ─────────────────────────────────────────────────────────────────────
let selContainer   = null;
let selCommand     = null;
let selSession     = null;   // session name for selected command
let activeStream   = null;   // EventSource
let streamSession  = null;   // session name currently streaming
let allSessions    = [];

// ── Polling ───────────────────────────────────────────────────────────────────
function refreshAll() {
  loadSessions();
  loadToolboxes();
}
setInterval(refreshAll, 8000);

// ── Host system stats (footer) ────────────────────────────────────────────────
function fmtKB(kb) {
  const g = kb / (1024 * 1024);
  if (g >= 1024) return (g / 1024).toFixed(2) + 'T';
  if (g >= 1) return g.toFixed(g < 10 ? 2 : 1) + 'G';
  return (kb / 1024).toFixed(0) + 'M';
}
function coreColor(p) { return p < 50 ? 'var(--ok)' : p < 85 ? 'var(--warn)' : 'var(--err)'; }
function fmtUptime(sec) {
  sec = Math.floor(sec || 0);
  const d = Math.floor(sec / 86400); sec %= 86400;
  const h = Math.floor(sec / 3600);  sec %= 3600;
  const m = Math.floor(sec / 60);
  return (d ? d + 'd ' : '') + String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}

async function loadStats() {
  const res = await fetch('/api/stats').catch(() => null);
  if (!res) return;
  const s = await res.json();
  if (!s || !Array.isArray(s.cpu_cores)) return;

  const cont = document.getElementById('sbCores');
  if (cont.children.length !== s.cpu_cores.length) {
    cont.innerHTML = s.cpu_cores.map(() => '<div class="sb-core"><i></i></div>').join('');
  }
  s.cpu_cores.forEach((p, i) => {
    const core = cont.children[i];
    core.firstChild.style.height = p + '%';
    core.firstChild.style.background = coreColor(p);
    core.title = `core ${i}: ${p.toFixed(1)}%`;
  });
  document.getElementById('sbCpuPct').textContent = Math.round(s.cpu_overall) + '%';

  const memPct = s.mem_total_kb ? (s.mem_used_kb / s.mem_total_kb * 100) : 0;
  document.getElementById('sbMemFill').style.width = memPct + '%';
  document.getElementById('sbMemTxt').textContent = `${fmtKB(s.mem_used_kb)}/${fmtKB(s.mem_total_kb)}`;

  const swPct = s.swap_total_kb ? (s.swap_used_kb / s.swap_total_kb * 100) : 0;
  document.getElementById('sbSwpFill').style.width = swPct + '%';
  document.getElementById('sbSwpTxt').textContent =
    s.swap_total_kb ? `${fmtKB(s.swap_used_kb)}/${fmtKB(s.swap_total_kb)}` : 'off';

  const diskPct = s.disk_total_kb ? (s.disk_used_kb / s.disk_total_kb * 100) : 0;
  document.getElementById('sbDiskFill').style.width = diskPct + '%';
  const dtxt = document.getElementById('sbDiskTxt');
  dtxt.textContent = `${fmtKB(s.disk_used_kb)} used · ${fmtKB(s.disk_free_kb)} free`;
  dtxt.title = `${fmtKB(s.disk_used_kb)} of ${fmtKB(s.disk_total_kb)} used (${diskPct.toFixed(0)}%)`;

  document.getElementById('sbLoad').textContent = (s.load || []).join('  ');
  document.getElementById('sbTasks').textContent = `${s.tasks} tasks, ${s.running} run`;
  document.getElementById('sbUptime').textContent = fmtUptime(s.uptime);
}
loadStats();
setInterval(loadStats, 2000);

// ── Sessions list ─────────────────────────────────────────────────────────────
async function loadSessions() {
  const res  = await fetch('/api/sessions').catch(() => null);
  if (!res) return;
  allSessions = await res.json();

  const count = allSessions.length;
  document.getElementById('sessionCount').textContent =
    count === 1 ? '1 session' : `${count} sessions`;

  // Host maintenance dot: pulse green only while a host command is running.
  const hostDot = document.getElementById('hostDot');
  if (hostDot) {
    const hostRunning = allSessions.some(s => s.name.startsWith('__host__'));
    hostDot.className = 'status-dot ' + (hostRunning ? 'up' : 'down');
  }

  const el = document.getElementById('sessionTabs');
  if (!count) {
    el.innerHTML = '<span class="tabs-empty" id="tabsEmpty">no running sessions — hit Launch to start one</span>';
  } else {
    el.innerHTML = allSessions.map(s => `
      <div class="session-tab ${streamSession === s.name ? 'selected' : ''}"
           role="tab" tabindex="0"
           aria-label="Attach to session ${esc(s.name)}"
           aria-selected="${streamSession === s.name ? 'true' : 'false'}"
           onclick="attachSession('${esc(s.name)}')">
        <div class="session-dot" aria-hidden="true"></div>
        <span class="session-name">${esc(s.name)}</span>
        <button class="session-kill" data-tip="Kill session" aria-label="Kill session ${esc(s.name)}"
                onclick="event.stopPropagation(); killSession('${esc(s.name)}')">✕</button>
      </div>
    `).join('');
  }

  // Keep the action buttons + context pill in sync with the (possibly changed)
  // live-session list. Without this, an ended session leaves stale Kill/Reconnect
  // buttons behind because nothing re-evaluates them after the list reloads.
  updateCmdButtons();
  updateCtxPill();
}

async function killSession(name) {
  await fetch(`/api/kill/${encodeURIComponent(name)}`, { method: 'POST' });
  if (streamSession === name) closeStream();
  refreshAll();
  updateCmdButtons();
}

// ── Toolbox list ──────────────────────────────────────────────────────────────
async function loadToolboxes() {
  const res = await fetch('/api/toolboxes').catch(() => null);
  if (!res) return;
  const boxes = await res.json();
  const el = document.getElementById('toolboxList');

  if (!boxes.length) {
    el.innerHTML = '<div class="empty-msg">no toolboxes found</div>';
    return;
  }
  el.innerHTML = boxes.map(b => `
    <div class="toolbox-item ${selContainer === b.name ? 'selected' : ''}"
         role="button" tabindex="0"
         aria-label="Toolbox ${esc(b.name)}, ${b.running ? 'running' : 'stopped'}${b.active_sessions.length ? ', ' + b.active_sessions.length + ' active session(s)' : ''}"
         ${selContainer === b.name ? 'aria-current="true"' : ''}
         onclick="selectToolbox('${esc(b.name)}', '${esc(b.id)}')"
         id="tb-${esc(b.id)}">
      <div class="status-dot ${b.running ? 'up' : 'down'}" aria-hidden="true"></div>
      <div class="tb-info">
        <div class="tb-name">${esc(b.name)}</div>
        <div class="tb-meta">
          <span>${esc(b.id.substring(0,8))}</span>
          ${b.active_sessions.length
            ? `<span class="tb-sessions-count">▶ ${b.active_sessions.length}</span>`
            : ''}
        </div>
      </div>
    </div>
  `).join('');

  // Footer summary (only meaningful before a toolbox is picked).
  const ls = document.getElementById('launcherStatus');
  if (ls && !selContainer) {
    ls.textContent = `${boxes.length} toolbox${boxes.length === 1 ? '' : 'es'} · pick one to see its commands`;
  }
}

// ── Select toolbox ────────────────────────────────────────────────────────────
async function selectToolbox(name, id) {
  selContainer = name;
  selCommand   = null;
  selSession   = null;

  document.querySelectorAll('.toolbox-item').forEach(e => { e.classList.remove('selected'); e.removeAttribute('aria-current'); });
  const sel = document.getElementById(`tb-${id}`);
  if (sel) { sel.classList.add('selected'); sel.setAttribute('aria-current', 'true'); }

  document.getElementById('cmdPlaceholder').style.display = 'none';
  document.getElementById('cmdInner').style.display = 'flex';
  const isHost = name === '__host__';
  document.getElementById('ctxLabel').textContent = isHost ? 'runs on:' : 'container:';
  document.getElementById('ctxContainer').textContent = isHost ? 'host (no container)' : name;
  document.getElementById('ctxSessionPill').innerHTML = '';

  const cl = document.getElementById('cmdList');
  cl.innerHTML = '<div style="font-family:var(--mono);font-size:11px;color:var(--dim)"><span class="spinner"></span> loading…</div>';
  updateCmdButtons();

  const res  = await fetch(`/api/commands/${encodeURIComponent(name)}`).catch(() => null);
  if (!res) { cl.innerHTML = '<div class="empty-msg">error loading commands</div>'; return; }
  const cmds = await res.json();

  // Store commands in a JS variable so onclick can index into it safely
  window._currentCmds = cmds;

  cl.innerHTML = cmds.map((c, i) => `
    <div class="cmd-item ${c.running ? 'is-running' : ''}" role="listitem"
         onclick="selectCmd(this, ${i})">
      <span class="cmd-num">${i+1}</span>
      <span class="cmd-main">
        <span class="cmd-toprow">
          ${c.label ? `<span class="cmd-label">${esc(c.label)}</span>` : ''}
          ${c.running ? '<span class="cmd-running-tag">▶ running</span>' : ''}
        </span>
        ${c.description ? `<span class="cmd-desc" title="${esc(c.description)}">${esc(c.description)}</span>` : ''}
        <button class="cmd-toggle" onclick="event.stopPropagation(); toggleCmdCode(this)">‹/› show command</button>
        <code class="cmd-code" hidden>${esc(maskSecrets(c.command))}</code>
      </span>
      <span class="cmd-actions">
        <button class="cmd-run-btn" title="${c.running ? 'Restart this command' : 'Run this command'}"
                onclick="event.stopPropagation(); runCmd(this, ${i})">${c.running ? '↺ Restart' : '▶ Run'}</button>
      </span>
    </div>
  `).join('');
  if (!cmds.length) cl.innerHTML = '<div class="empty-msg">no commands configured for this toolbox</div>';

  const ls = document.getElementById('launcherStatus');
  if (ls) ls.textContent = `${isHost ? 'host' : name} · ${cmds.length} command${cmds.length === 1 ? '' : 's'}`;
}

// Mask secrets (API keys) for DISPLAY only — the real command is still run as-is.
function maskSecrets(s) {
  return String(s)
    .replace(/(--api-key[ =]+)(\S+)/g, '$1sk-••••')
    .replace(/\bsk-[A-Za-z0-9]{6,}\b/g, 'sk-••••');
}

// Reveal / hide the raw command inside a card.
function toggleCmdCode(btn) {
  const code = btn.parentElement.querySelector('.cmd-code');
  const show = code.hasAttribute('hidden');
  if (show) code.removeAttribute('hidden'); else code.setAttribute('hidden', '');
  btn.textContent = show ? '‹/› hide command' : '‹/› show command';
}

// Run a command straight from its card (selects it, then runs).
async function runCmd(btn, idx) {
  selectCmd(btn.closest('.cmd-item'), idx);
  await doRun();
}

// ── Select command ────────────────────────────────────────────────────────────
function selectCmd(el, idx) {
  const c = window._currentCmds[idx];
  selCommand = c.command;
  selSession = c.session;
  document.querySelectorAll('.cmd-item').forEach(e => e.classList.remove('selected'));
  el.classList.add('selected');
  setRunState('');
  updateCmdButtons();
  updateCtxPill();
}

function updateCtxPill() {
  const pill = document.getElementById('ctxSessionPill');
  if (!selSession) { pill.innerHTML = ''; return; }
  const live = allSessions.some(s => s.name === selSession);
  pill.innerHTML = live
    ? `session: <span class="pill pill-cyan">${esc(selSession)}</span>`
    : `session: <span class="pill" style="color:var(--dim);border:1px solid var(--border2)">${esc(selSession)}</span>`;
}

function updateCmdButtons() {
  const btnAttach = document.getElementById('btnAttach');
  const btnKill   = document.getElementById('btnKill');
  const hasCmd    = !!selCommand;
  const isLive    = selSession && allSessions.some(s => s.name === selSession);
  const streaming = streamSession === selSession && !!activeStream;

  // Running is done per-command from each card's ▶ button. The bottom row only
  // carries session controls (Reconnect / Kill) for the live session.
  btnAttach.style.display = hasCmd && isLive && !streaming ? '' : 'none';
  btnKill.style.display   = hasCmd && isLive ? '' : 'none';
}

// ── Run ───────────────────────────────────────────────────────────────────────
async function doRun() {
  if (!selContainer || !selCommand) return;
  closeStream();

  // Kill existing session first (restart behaviour)
  const existing = allSessions.find(s => s.name === selSession);
  if (existing) {
    setRunState('restarting…', 'live');
    await fetch(`/api/kill/${encodeURIComponent(existing.name)}`, { method: 'POST' });
    await new Promise(r => setTimeout(r, 400));
    await loadSessions();
  }

  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ container: selContainer, command: selCommand }),
  });
  const data = await res.json();
  if (data.error) { setRunState('error: ' + data.error, 'err'); return; }

  const session = data.session;
  selSession = session;

  openStream(session, `▶ ${selContainer} › ${maskSecrets(selCommand)}`);
  closeModal('launcherModal');   // launch done — reveal the streaming output
  refreshAll();
  updateCmdButtons();
  updateCtxPill();
}

// ── Attach to existing session ────────────────────────────────────────────────
async function doAttach() {
  if (!selSession) return;
  openStream(selSession, `⟳ reconnecting to '${selSession}'…`);
  updateCmdButtons();
}

async function attachSession(name) {
  // Called from a session tab above the terminal.
  openStream(name, `⟳ attaching to '${name}'…`);

  // Update the active-tab highlight (match by session name).
  document.querySelectorAll('.session-tab').forEach(e => {
    const match = e.querySelector('.session-name')?.textContent === name;
    e.classList.toggle('selected', match);
    e.setAttribute('aria-selected', match ? 'true' : 'false');
  });
}

// ── Kill ──────────────────────────────────────────────────────────────────────
async function doKill() {
  if (!selSession) return;
  await killSession(selSession);
  setRunState('killed', 'err');
  updateCmdButtons();
  updateCtxPill();
}

// ── Stream helpers ────────────────────────────────────────────────────────────
// The server tails a per-session log file by byte offset. Completed lines carry
// an SSE id (= byte offset); EventSource replays Last-Event-ID on auto-reconnect,
// so reconnects resume exactly — no duplicate output. In-progress lines (e.g.
// progress bars) arrive with {partial:true} and update a single live element.
function openStream(session, header) {
  closeStream();
  streamSession = session;
  clearTerm();
  partialEl = null;
  if (header) { termLine('meta', header); termLine('sep', '─'.repeat(72)); }

  setTermTitle(session, 'live');
  setRunState('streaming…', 'live');

  const es = new EventSource(`/api/stream/${encodeURIComponent(session)}`);
  activeStream = es;

  es.onmessage = (ev) => {
    if (ev.data.startsWith(':')) return; // SSE comment keepalive
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }

    if (msg.error)        setRunState('error: ' + msg.error, 'err');
    else if (msg.meta)    { finalizePartial(); termLine('meta', msg.line); }
    else if (msg.partial) termPartial(msg.line);
    else if (msg.line !== undefined) { finalizePartial(); termLine('', msg.line); }

    if (msg.done) {
      finalizePartial();
      es.close(); activeStream = null;
      // The session is gone: drop it from the cached list immediately so the
      // action buttons recompute as "ended" right away (no one-frame flash of
      // Kill/Reconnect), then reconcile with the server in the background.
      allSessions = allSessions.filter(s => s.name !== session);
      setTermTitle(session, 'history');
      if (!msg.error) setRunState('session ended', '');
      refreshAll();
      updateCmdButtons();
      updateCtxPill();
    }
  };

  // On a transient drop the browser auto-reconnects (resuming via Last-Event-ID);
  // just reflect the state. A genuinely gone session arrives as a `done` message.
  es.onerror = () => {
    if (activeStream === es) setRunState('reconnecting…', 'live');
  };
}

function closeStream() {
  if (activeStream) { activeStream.close(); activeStream = null; }
  streamSession = null;
  partialEl = null;
}

// ── Terminal ──────────────────────────────────────────────────────────────────
// High-throughput output (e.g. `podman pull` printing thousands of "Copying
// blob …" lines/sec) is buffered and flushed once per animation frame. Doing a
// layout read (nearBottom) + scroll on *every* line forced two synchronous
// reflows per line, which froze the tab ("page not responding"). Batching keeps
// it to one reflow per frame regardless of output rate.
const MAX_TERM_LINES = 6000;   // cap DOM size for long-running servers
let partialEl = null;          // the current in-progress (no-newline) line, if any
let _termEvents = [];          // queued render ops, flushed on rAF
let _termFlush  = false;       // is a flush already scheduled?

function nearBottom(body) {
  return body.scrollHeight - body.scrollTop - body.clientHeight < 60;
}

function scheduleTermFlush() {
  // Cap the queue so a backgrounded tab (rAF paused) can't grow it unbounded.
  if (_termEvents.length > 8000) _termEvents.splice(0, _termEvents.length - MAX_TERM_LINES);
  if (_termFlush) return;
  _termFlush = true;
  requestAnimationFrame(flushTerm);
}

function flushTerm() {
  _termFlush = false;
  const body = document.getElementById('termBody');
  if (!body || !_termEvents.length) return;
  const events = _termEvents;
  _termEvents = [];

  const ph = body.querySelector('.placeholder');
  if (ph) ph.remove();

  const stick = nearBottom(body);   // single layout read for the whole batch

  for (const ev of events) {
    if (ev.t === 'finalize') {
      if (partialEl) { partialEl.remove(); partialEl = null; }
    } else if (ev.t === 'partial') {
      if (!partialEl || partialEl.parentNode !== body) {
        partialEl = document.createElement('div');
        partialEl.className = 'term-line partial';
        body.appendChild(partialEl);
      }
      partialEl.textContent = ev.text;
    } else {
      const d = document.createElement('div');
      d.className = `term-line ${ev.cls}`;
      d.textContent = ev.text;
      if (partialEl && partialEl.parentNode === body) body.insertBefore(d, partialEl);
      else body.appendChild(d);
    }
  }

  let over = body.childElementCount - MAX_TERM_LINES;
  while (over-- > 0 && body.firstElementChild) body.removeChild(body.firstElementChild);

  if (stick) body.scrollTop = body.scrollHeight;   // single layout write
}

function termLine(cls, text) {
  _termEvents.push({ t: 'line', cls, text });
  scheduleTermFlush();
}

function termPartial(text) {
  // Collapse rapid progress-bar updates: overwrite the last queued partial.
  const last = _termEvents[_termEvents.length - 1];
  if (last && last.t === 'partial') last.text = text;
  else _termEvents.push({ t: 'partial', text });
  scheduleTermFlush();
}

function finalizePartial() {
  _termEvents.push({ t: 'finalize' });
  scheduleTermFlush();
}

function clearTerm() {
  partialEl = null;
  _termEvents = [];
  document.getElementById('termBody').innerHTML =
    '<div class="placeholder"><div class="placeholder-glyph">⬡</div><div>select a toolbox and command, then hit run</div><div style="color:var(--border2);font-size:10px;margin-top:6px;">sessions persist after closing the browser</div></div>';
}

function setTermTitle(name, badge) {
  document.getElementById('termTitle').textContent = name;
  const b = document.getElementById('termBadge');
  if (badge === 'live') {
    b.style.display = ''; b.className = 'term-badge live'; b.textContent = '● live';
  } else if (badge === 'history') {
    b.style.display = ''; b.className = 'term-badge history'; b.textContent = 'history';
  } else if (badge === 'idle') {
    b.style.display = ''; b.className = 'term-badge idle'; b.textContent = 'idle';
  } else {
    b.style.display = 'none';
  }
}

function setRunState(msg, cls) {
  const el = document.getElementById('runState');
  el.textContent = msg;
  el.className = `run-state ${cls || ''}`;
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Config editor ───────────────────────────────────────────────────────────
let currentFile = 'commands.yaml';

function setConfigStatus(msg, cls) {
  const el = document.getElementById('configStatus');
  el.textContent = msg;
  el.className = `modal-status ${cls || 'dim'}`;
}

const NEW_INI_TEMPLATE =
`# llama.cpp preset file — used via: llama-server --models-preset <this file>
[*]
# Global defaults applied to every preset below
n-gpu-layers = 999
flash-attn   = on
jinja        = true

[preset/my-model]
model    = /home/maintenance/models/<your-model>/<file>.gguf
ctx-size = 32768
temp     = 0.7
top-p    = 0.95
`;

// Rebuild the file <select> from the server list, plus a "new .ini" entry.
async function populateFiles() {
  const sel = document.getElementById('configFile');
  const fres = await fetch('/api/config/files').catch(() => null);
  if (!fres) return;
  const fd = await fres.json();
  sel.innerHTML = fd.files.map(f =>
    `<option value="${esc(f.id)}">${esc(f.id)}${f.exists ? '' : ' (new)'}</option>`
  ).join('') + `<option value="__new__">➕ new .ini…</option>`;
  if (!fd.files.some(f => f.id === currentFile)) currentFile = 'commands.yaml';
  sel.value = currentFile;
}

async function openConfig() {
  openModal('configModal', 'configText');
  setConfigStatus('loading…', 'dim');
  document.getElementById('configText').value = '';
  await populateFiles();
  await loadConfigFile(currentFile);
}

async function newIniFile() {
  const sel = document.getElementById('configFile');
  let name = (await uiPrompt({
    title: 'New .ini preset file',
    message: 'Filename (created in the models dir):',
    value: 'my-models.ini', placeholder: 'my-models.ini', confirmText: 'Create',
  }) || '').trim();
  if (!name) { sel.value = currentFile; return; }
  if (!name.endsWith('.ini')) name += '.ini';
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.ini$/.test(name)) {
    setConfigStatus('invalid name — use letters/digits/._- and a .ini extension', 'err');
    sel.value = currentFile;
    return;
  }
  // Add a pending option for it (real one appears after first save).
  if (![...sel.options].some(o => o.value === name)) {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name + ' (new)';
    sel.insertBefore(opt, sel.querySelector('option[value="__new__"]'));
  }
  loadConfigFile(name);
}

async function loadConfigFile(id) {
  if (id === '__new__') { newIniFile(); return; }
  currentFile = id;
  document.getElementById('configFile').value = id;
  setConfigStatus('loading…', 'dim');
  document.getElementById('configText').value = '';
  const res = await fetch(`/api/config?file=${encodeURIComponent(id)}`).catch(() => null);
  if (!res) { setConfigStatus('failed to load file', 'err'); return; }
  const d = await res.json();
  let text = d.text;
  if (!d.exists && d.type === 'ini' && !text) text = NEW_INI_TEMPLATE;  // starter for new files
  document.getElementById('configText').value = text;
  document.getElementById('configPath').textContent = d.path || '';

  const tokenRow = document.getElementById('tokenRow');
  if (d.token_required) {
    tokenRow.style.display = 'flex';
    document.getElementById('configToken').value = localStorage.getItem('toolboxToken') || '';
  } else {
    tokenRow.style.display = 'none';
  }
  setConfigStatus(d.exists ? `loaded (${d.type})` : 'new file — edit and Save to create it', 'dim');
  document.getElementById('configText').focus();
}

function closeConfig() {
  closeModal('configModal');
}

async function validateConfig() {
  setConfigStatus('validating…', 'dim');
  const text = document.getElementById('configText').value;
  const res = await fetch(`/api/config/validate?file=${encodeURIComponent(currentFile)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).catch(() => null);
  if (!res) { setConfigStatus('validation request failed', 'err'); return false; }
  const d = await res.json();
  setConfigStatus(d.message, d.ok ? 'ok' : 'err');
  return d.ok;
}

async function saveConfig() {
  const btn = document.getElementById('configSave');
  btn.disabled = true;
  setConfigStatus('saving…', 'dim');
  const text  = document.getElementById('configText').value;
  const token = document.getElementById('configToken').value;
  if (document.getElementById('tokenRow').style.display !== 'none') {
    localStorage.setItem('toolboxToken', token);
  }
  const res = await fetch(`/api/config?file=${encodeURIComponent(currentFile)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': token },
    body: JSON.stringify({ text }),
  }).catch(() => null);
  btn.disabled = false;
  if (!res) { setConfigStatus('save request failed', 'err'); return; }
  const d = await res.json();
  setConfigStatus(d.message, d.ok ? 'ok' : 'err');
  if (d.ok && currentFile === 'commands.yaml') {
    // Reflect the new commands immediately and re-load the open toolbox's list.
    refreshAll();
    if (selContainer) selectToolbox(selContainer, '');
  } else if (d.ok) {
    // A new .ini now exists on disk — refresh the selector so it's permanent.
    await populateFiles();
  }
}

// ── Command builder (form-based, no YAML) ──────────────────────────────────────
let cbState = { rules: [], toolboxes: [], editing: null, token_required: false, ruamel: true };

function cbSetStatus(msg, cls) {
  const el = document.getElementById('cbStatus');
  el.textContent = msg; el.className = `modal-status ${cls || 'dim'}`;
}

async function openCmdBuilder(prefill) {
  openModal('cmdBuilderModal', 'cbTarget');
  cbResetForm();
  cbSetStatus('loading…', 'dim');
  await cbLoad();
  if (prefill) {
    if (prefill.label) document.getElementById('cbLabel').value = prefill.label;
    if (prefill.cmd) document.getElementById('cbCmd').value = prefill.cmd;
    if (prefill.preferMatch) {           // pick an existing rule for e.g. 'vllm' if present
      const sel = document.getElementById('cbTarget');
      const opt = [...sel.options].find(o => o.textContent.toLowerCase().includes(prefill.preferMatch));
      if (opt) { sel.value = opt.value; cbTargetChanged(); }
    }
    cbSetStatus('pre-filled from an unused model — review and Add command', 'dim');
    document.getElementById('cbCmd').focus();
  }
}

async function cbLoad() {
  const res = await fetch('/api/commands').catch(() => null);
  if (!res) { cbSetStatus('failed to load commands', 'err'); return; }
  const d = await res.json();
  cbState.rules = d.rules || [];
  cbState.toolboxes = d.toolboxes || [];
  cbState.token_required = !!d.token_required;
  cbState.ruamel = d.ruamel !== false;
  cbRenderTargets();
  cbRenderToolboxList();
  cbRenderList();
  document.getElementById('cbTokenRow').style.display = cbState.token_required ? 'flex' : 'none';
  if (cbState.token_required) document.getElementById('cbToken').value = localStorage.getItem('toolboxToken') || '';
  if (!cbState.ruamel) {
    cbSetStatus("Form needs the 'ruamel.yaml' package — use the ⚙ raw editor for now.", 'err');
    document.getElementById('cbSubmit').disabled = true;
  } else {
    document.getElementById('cbSubmit').disabled = false;
    cbSetStatus(`${cbState.rules.length} rule(s) loaded`, 'dim');
  }
}

// Fill the "Show this command for…" picker from existing rules + a "new match" option.
function cbRenderTargets() {
  const sel = document.getElementById('cbTarget');
  const opts = cbState.rules.map(r =>
    `<option value="existing:${r.index}">${esc(r.label)}</option>`).join('');
  sel.innerHTML = opts + `<option value="new">➕ a new toolbox match…</option>`;
  cbTargetChanged();
}

function cbRenderToolboxList() {
  document.getElementById('cbToolboxList').innerHTML =
    cbState.toolboxes.map(n => `<option value="${esc(n)}">`).join('');
}

function cbTargetChanged() {
  const isNew = document.getElementById('cbTarget').value === 'new';
  document.getElementById('cbNewMatch').style.display = isNew ? 'flex' : 'none';
  if (isNew) cbMatchTypeChanged();
}

function cbMatchTypeChanged() {
  const t = document.getElementById('cbMatchType').value;
  document.getElementById('cbMatchValueField').style.display = (t === 'default') ? 'none' : 'flex';
}

// Render the read-only list of existing rules and their commands, with edit/delete.
function cbRenderList() {
  const wrap = document.getElementById('cbList');
  if (!cbState.rules.length) { wrap.innerHTML = ''; return; }
  wrap.innerHTML = cbState.rules.map(r => {
    const cmds = r.commands.map((c, ci) => `
      <div class="cb-cmd">
        <div class="cb-cmd-main">
          ${c.label ? `<div class="cb-cmd-label">${esc(c.label)}</div>` : ''}
          <div class="cb-cmd-code">${esc(c.cmd)}</div>
          ${c.description ? `<div class="cb-cmd-desc">${esc(c.description)}</div>` : ''}
        </div>
        <div class="cb-cmd-actions">
          <button class="cb-mini" onclick="cbEdit(${r.index},${ci})">edit</button>
          <button class="cb-mini danger" onclick="cbDelete(${r.index},${ci})">delete</button>
        </div>
      </div>`).join('');
    return `<div class="cb-rule">
      <div class="cb-rule-head">for <b>${esc(r.label)}</b></div>${cmds}</div>`;
  }).join('');
}

function cbResetForm() {
  cbState.editing = null;
  document.getElementById('cbFormTitle').textContent = 'Add a command';
  document.getElementById('cbSubmit').textContent = 'Add command';
  document.getElementById('cbCancelEdit').style.display = 'none';
  document.getElementById('cbTarget').disabled = false;
  ['cbLabel', 'cbCmd', 'cbDesc', 'cbMatchValue'].forEach(id => document.getElementById(id).value = '');
  const sel = document.getElementById('cbTarget');
  if (sel.options.length) sel.selectedIndex = 0;
  cbTargetChanged();
}

function cbEdit(ri, ci) {
  const rule = cbState.rules.find(r => r.index === ri);
  if (!rule) return;
  const c = rule.commands[ci];
  cbState.editing = { rule_index: ri, cmd_index: ci };
  document.getElementById('cbFormTitle').textContent = `Edit command (for ${rule.label})`;
  document.getElementById('cbSubmit').textContent = 'Save changes';
  document.getElementById('cbCancelEdit').style.display = 'inline-block';
  // When editing, the command stays in its current rule — lock the target picker.
  document.getElementById('cbTarget').value = `existing:${ri}`;
  document.getElementById('cbTarget').disabled = true;
  cbTargetChanged();
  document.getElementById('cbLabel').value = c.label || '';
  document.getElementById('cbCmd').value = c.cmd || '';
  document.getElementById('cbDesc').value = c.description || '';
  document.getElementById('cmdBuilderModal').querySelector('.modal-body').scrollTop = 0;
  document.getElementById('cbCmd').focus();
}

function cbToken() {
  const t = document.getElementById('cbToken').value;
  if (cbState.token_required) localStorage.setItem('toolboxToken', t);
  return t;
}

async function cbPost(payload) {
  const res = await fetch('/api/commands', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': cbToken() },
    body: JSON.stringify(payload),
  }).catch(() => null);
  if (!res) { cbSetStatus('request failed', 'err'); return false; }
  const d = await res.json();
  cbSetStatus(d.message, d.ok ? 'ok' : 'err');
  if (d.ok) {
    await cbLoad();
    cbResetForm();
    refreshAll();
    if (selContainer) selectToolbox(selContainer, '');
  }
  return d.ok;
}

async function cbSubmit() {
  const cmd = document.getElementById('cbCmd').value.trim();
  if (!cmd) { cbSetStatus('Enter a command first.', 'err'); document.getElementById('cbCmd').focus(); return; }
  const label = document.getElementById('cbLabel').value.trim();
  const description = document.getElementById('cbDesc').value.trim();
  const btn = document.getElementById('cbSubmit');
  btn.disabled = true;

  let payload;
  if (cbState.editing) {
    payload = { op: 'update_command', ...cbState.editing, cmd, label, description };
  } else {
    const tgt = document.getElementById('cbTarget').value;
    let target;
    if (tgt === 'new') {
      const type = document.getElementById('cbMatchType').value;
      const value = document.getElementById('cbMatchValue').value.trim();
      if (type !== 'default' && !value) {
        cbSetStatus('Enter the text to match toolbox names against.', 'err');
        btn.disabled = false; document.getElementById('cbMatchValue').focus(); return;
      }
      target = { kind: 'new', type, value };
    } else {
      target = { kind: 'existing', index: parseInt(tgt.split(':')[1], 10) };
    }
    payload = { op: 'add_command', target, cmd, label, description };
  }
  await cbPost(payload);
  btn.disabled = false;
}

async function cbDelete(ri, ci) {
  const rule = cbState.rules.find(r => r.index === ri);
  const c = rule && rule.commands[ci];
  const name = (c && (c.label || c.cmd)) || 'this command';
  const ok = await uiConfirm({
    title: 'Delete command',
    message: `Remove “${name}”?\nIf it's the last command for this match, the whole rule is removed.`,
    confirmText: 'Delete', danger: true,
  });
  if (!ok) return;
  await cbPost({ op: 'delete_command', rule_index: ri, cmd_index: ci });
}

// ── Model preset builder (form-based, no .ini editing) ──────────────────────────
let pbState = { files: [], common: [], suggestions: [], editing: null, token_required: false };

function pbSetStatus(msg, cls) {
  const el = document.getElementById('pbStatus');
  el.textContent = msg; el.className = `modal-status ${cls || 'dim'}`;
}

async function openPresetBuilder(prefill) {
  openModal('presetBuilderModal', 'pbFile');
  pbBuildGrid();
  pbResetForm();
  pbSetStatus('loading…', 'dim');
  await pbLoad();
  if (prefill) {
    if (prefill.model) document.getElementById('pbModel').value = prefill.model;
    if (prefill.name) document.getElementById('pbName').value = prefill.name;
    pbSetStatus('pre-filled from an unused model — review and Add preset', 'dim');
    document.getElementById('pbName').focus();
  }
}

async function pbLoad() {
  const res = await fetch('/api/presets').catch(() => null);
  if (!res) { pbSetStatus('failed to load presets', 'err'); return; }
  const d = await res.json();
  pbState.files = d.files || [];
  pbState.common = d.common_fields || [];
  pbState.suggestions = d.model_suggestions || [];
  pbState.token_required = !!d.token_required;
  pbBuildGrid();
  pbRenderModelList();
  pbRenderFileSelect();          // → pbFileChanged() renders the selected file's globals + presets
  document.getElementById('pbTokenRow').style.display = pbState.token_required ? 'flex' : 'none';
  if (pbState.token_required) document.getElementById('pbToken').value = localStorage.getItem('toolboxToken') || '';
  pbSetStatus(`${pbState.files.length} preset file(s) loaded`, 'dim');
}

// The currently-selected existing file (null when "new file" is chosen).
function pbCurrentFile() {
  const id = document.getElementById('pbFile').value;
  return pbState.files.find(f => f.id === id) || null;
}

// Build the labelled numeric fields from the server's common-field list.
function pbBuildGrid() {
  const grid = document.getElementById('pbGrid');
  const fields = pbState.common.length ? pbState.common
    : ['ctx-size', 'parallel', 'temp', 'top-p', 'top-k', 'min-p', 'repeat-penalty'];
  if (grid.dataset.built === fields.join(',')) return;
  grid.innerHTML = fields.map(f => `
    <label class="cb-field">
      <span>${esc(f)}</span>
      <input id="pbf_${esc(f)}" data-field="${esc(f)}" autocomplete="off" placeholder="—">
    </label>`).join('');
  grid.dataset.built = fields.join(',');
}

function pbRenderFileSelect() {
  const sel = document.getElementById('pbFile');
  const prev = sel.value;
  sel.innerHTML = pbState.files.map(f =>
    `<option value="${esc(f.id)}">${esc(f.id)}</option>`).join('')
    + `<option value="__new__">➕ a new .ini file…</option>`;
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
  pbFileChanged();
}

// Custom model-file suggestion dropdown (replaces the native datalist, which
// clipped long .gguf paths to the input width). Shows filename + dimmed dir, wraps.
function pbRenderModelList() { /* suggestions are rendered on demand by pbModelFilter */ }

let pbAcIndex = -1;

function pbModelFilter() {
  const inp = document.getElementById('pbModel');
  const list = document.getElementById('pbModelAcList');
  const q = inp.value.trim().toLowerCase();
  let items = pbState.suggestions || [];
  if (q) items = items.filter(s => s.toLowerCase().includes(q));
  items = items.slice(0, 60);
  if (!items.length) { list.hidden = true; return; }
  pbAcIndex = -1;
  list.innerHTML = items.map(s => {
    const base = s.split('/').pop();
    const dir = s.slice(0, s.length - base.length);
    return `<div class="cb-ac-item" data-val="${esc(s)}" onmousedown="event.preventDefault(); pbModelPick(this.dataset.val)">
      <div class="cb-ac-name">${esc(base)}</div>${dir ? `<div class="cb-ac-dir">${esc(dir)}</div>` : ''}
    </div>`;
  }).join('');
  pbModelPosition();
  list.hidden = false;
}

function pbModelPosition() {
  const r = document.getElementById('pbModel').getBoundingClientRect();
  const list = document.getElementById('pbModelAcList');
  list.style.left = r.left + 'px';
  list.style.top = (r.bottom + 3) + 'px';
  list.style.width = r.width + 'px';
}

function pbModelPick(val) {
  document.getElementById('pbModel').value = val;
  document.getElementById('pbModelAcList').hidden = true;
}

function pbModelBlur() {
  // delay so a click/mousedown on an item registers before we hide
  setTimeout(() => { document.getElementById('pbModelAcList').hidden = true; }, 120);
}

function pbModelKey(e) {
  const list = document.getElementById('pbModelAcList');
  if (list.hidden) return;
  const items = [...list.querySelectorAll('.cb-ac-item')];
  if (e.key === 'ArrowDown') { e.preventDefault(); pbAcIndex = Math.min(pbAcIndex + 1, items.length - 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); pbAcIndex = Math.max(pbAcIndex - 1, 0); }
  else if (e.key === 'Enter') { if (pbAcIndex >= 0) { e.preventDefault(); pbModelPick(items[pbAcIndex].dataset.val); } return; }
  else if (e.key === 'Escape') { list.hidden = true; return; }
  else return;
  items.forEach((it, i) => it.classList.toggle('active', i === pbAcIndex));
  if (items[pbAcIndex]) items[pbAcIndex].scrollIntoView({ block: 'nearest' });
}

// The dropdown is fixed-positioned, so when the *form pane* scrolls we follow the
// input. But scrolling *inside the dropdown's own list* must not close it.
document.addEventListener('scroll', (e) => {
  const l = document.getElementById('pbModelAcList');
  if (!l || l.hidden) return;
  if (e.target instanceof Node && l.contains(e.target)) return;   // scrolling the list itself
  const r = document.getElementById('pbModel').getBoundingClientRect();
  const body = document.querySelector('#presetBuilderModal .modal-body');
  const bb = body ? body.getBoundingClientRect() : { top: 0, bottom: innerHeight };
  if (r.bottom < bb.top || r.bottom > bb.bottom) { l.hidden = true; }  // input scrolled out of view
  else { pbModelPosition(); }                                          // otherwise keep it attached
}, true);

// Selecting a file hot-reloads its existing presets + global defaults into view.
function pbFileChanged() {
  const isNew = document.getElementById('pbFile').value === '__new__';
  document.getElementById('pbNewFileField').style.display = isNew ? 'flex' : 'none';
  pbLoadGlobals();
  pbRenderList();
}

// Show the [*] defaults of the selected existing file (hidden for a brand-new file).
function pbLoadGlobals() {
  const card = document.getElementById('pbGlobalsCard');
  const f = pbCurrentFile();
  if (!f) { card.style.display = 'none'; return; }
  card.style.display = '';
  document.getElementById('pbGlobalsFile').textContent = f.id;
  document.getElementById('pbGlobals').value = f.globals_text || '';
}

// List the existing presets of the selected file only, with edit/delete.
function pbRenderList() {
  const wrap = document.getElementById('pbList');
  const f = pbCurrentFile();
  if (!f) { wrap.innerHTML = ''; return; }
  if (!f.presets.length) {
    wrap.innerHTML = `<div class="cb-rule"><div class="cb-rule-head"><b>${esc(f.id)}</b> — no presets yet</div></div>`;
    return;
  }
  const rows = f.presets.map(p => {
    const parts = [];
    if (p.model) parts.push(p.model.split('/').pop());
    Object.entries(p.fields || {}).forEach(([k, v]) => parts.push(`${k}=${v}`));
    return `<div class="cb-cmd">
      <div class="cb-cmd-main">
        <div class="cb-cmd-label">${esc(p.name)}</div>
        <div class="cb-cmd-desc">${esc(parts.join('  ·  '))}</div>
      </div>
      <div class="cb-cmd-actions">
        <button class="cb-mini" onclick="pbEdit('${esc(f.id)}','${esc(p.name)}')">edit</button>
        <button class="cb-mini danger" onclick="pbDelete('${esc(f.id)}','${esc(p.name)}')">delete</button>
      </div>
    </div>`;
  }).join('');
  wrap.innerHTML = `<div class="cb-rule"><div class="cb-rule-head"><b>${esc(f.id)}</b> — ${f.presets.length} preset(s)</div>${rows}</div>`;
}

async function pbSaveGlobals() {
  const f = pbCurrentFile();
  if (!f) { pbSetStatus('Select an existing file first.', 'err'); return; }
  const btn = document.getElementById('pbGlobalsSave');
  btn.disabled = true;
  await pbPost({ op: 'update_globals', file: f.id, text: document.getElementById('pbGlobals').value });
  btn.disabled = false;
}

function pbReadFields() {
  const out = {};
  document.querySelectorAll('#pbGrid input[data-field]').forEach(inp => {
    out[inp.dataset.field] = inp.value.trim();
  });
  return out;
}

function pbResetForm() {
  pbState.editing = null;
  document.getElementById('pbFormTitle').textContent = 'Add a model preset';
  document.getElementById('pbSubmit').textContent = 'Add preset';
  document.getElementById('pbCancelEdit').style.display = 'none';
  document.getElementById('pbName').disabled = false;
  document.getElementById('pbFile').disabled = false;
  ['pbName', 'pbModel', 'pbAdvanced', 'pbNewFile'].forEach(id => document.getElementById(id).value = '');
  document.querySelectorAll('#pbGrid input[data-field]').forEach(i => i.value = '');
  pbFileChanged();
}

function pbEdit(fileId, name) {
  const f = pbState.files.find(x => x.id === fileId);
  const p = f && f.presets.find(x => x.name === name);
  if (!p) return;
  pbState.editing = { file: fileId, name };
  document.getElementById('pbFormTitle').textContent = `Edit preset “${name}” (in ${fileId})`;
  document.getElementById('pbSubmit').textContent = 'Save changes';
  document.getElementById('pbCancelEdit').style.display = 'inline-block';
  // On edit the file + name are fixed (rename = delete + add).
  const fileSel = document.getElementById('pbFile');
  if (![...fileSel.options].some(o => o.value === fileId)) {
    const o = document.createElement('option'); o.value = fileId; o.textContent = fileId; fileSel.appendChild(o);
  }
  fileSel.value = fileId; fileSel.disabled = true; pbFileChanged();
  const nm = document.getElementById('pbName'); nm.value = name; nm.disabled = true;
  document.getElementById('pbModel').value = p.model || '';
  // Known fields → their inputs; everything else → the advanced box.
  document.querySelectorAll('#pbGrid input[data-field]').forEach(i => i.value = '');
  const extra = [];
  Object.entries(p.fields || {}).forEach(([k, v]) => {
    const inp = document.getElementById('pbf_' + k);
    if (inp) inp.value = v; else extra.push(`${k} = ${v}`);
  });
  document.getElementById('pbAdvanced').value = extra.join('\n');
  document.getElementById('presetBuilderModal').querySelector('.modal-body').scrollTop = 0;
  document.getElementById('pbModel').focus();
}

function pbToken() {
  const t = document.getElementById('pbToken').value;
  if (pbState.token_required) localStorage.setItem('toolboxToken', t);
  return t;
}

async function pbPost(payload) {
  const res = await fetch('/api/presets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': pbToken() },
    body: JSON.stringify(payload),
  }).catch(() => null);
  if (!res) { pbSetStatus('request failed', 'err'); return false; }
  const d = await res.json();
  pbSetStatus(d.message, d.ok ? 'ok' : 'err');
  if (d.ok) { await pbLoad(); pbResetForm(); }
  return d.ok;
}

async function pbSubmit() {
  const name = document.getElementById('pbName').value.trim();
  const model = document.getElementById('pbModel').value.trim();
  if (!name) { pbSetStatus('Enter a preset name.', 'err'); document.getElementById('pbName').focus(); return; }
  if (!model) { pbSetStatus('Pick the model .gguf file.', 'err'); document.getElementById('pbModel').focus(); return; }
  const advanced = document.getElementById('pbAdvanced').value;
  const fields = pbReadFields();
  const btn = document.getElementById('pbSubmit');
  btn.disabled = true;

  let payload;
  if (pbState.editing) {
    payload = { op: 'update_preset', file: pbState.editing.file, name: pbState.editing.name, model, fields, advanced };
  } else {
    let file = document.getElementById('pbFile').value;
    if (file === '__new__') {
      file = document.getElementById('pbNewFile').value.trim();
      if (!file) { pbSetStatus('Enter a file name for the new .ini.', 'err'); btn.disabled = false; document.getElementById('pbNewFile').focus(); return; }
      if (!file.endsWith('.ini')) file += '.ini';
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.ini$/.test(file)) {
        pbSetStatus('Bad file name — use letters/digits/._- and a .ini extension.', 'err'); btn.disabled = false; return;
      }
    }
    payload = { op: 'add_preset', file, name, model, fields, advanced };
  }
  const ok = await pbPost(payload);
  if (ok && payload.file) pbSelectFile(payload.file);   // jump to the file we just wrote
  btn.disabled = false;
}

// Select an existing file in the dropdown (if present) and refresh its view.
function pbSelectFile(id) {
  const sel = document.getElementById('pbFile');
  if ([...sel.options].some(o => o.value === id)) { sel.value = id; pbFileChanged(); }
}

async function pbDelete(fileId, name) {
  const ok = await uiConfirm({
    title: 'Delete preset',
    message: `Remove preset “${name}” from ${fileId}?`,
    confirmText: 'Delete', danger: true,
  });
  if (!ok) return;
  await pbPost({ op: 'delete_preset', file: fileId, name });
}

// Close on Esc, save on Ctrl/Cmd+S while the editor is open.
document.addEventListener('keydown', (e) => {
  if (document.getElementById('launcherModal').classList.contains('open') && e.key === 'Escape') {
    closeModal('launcherModal'); return;
  }
  if (document.getElementById('presetBuilderModal').classList.contains('open') && e.key === 'Escape') {
    closeModal('presetBuilderModal'); return;
  }
  if (document.getElementById('cmdBuilderModal').classList.contains('open') && e.key === 'Escape') {
    closeModal('cmdBuilderModal'); return;
  }
  if (document.getElementById('modelsModal').classList.contains('open') && e.key === 'Escape') {
    closeModels(); return;
  }
  if (document.getElementById('toolboxModal').classList.contains('open') && e.key === 'Escape') {
    closeToolboxes(); return;
  }
  if (document.getElementById('logsModal').classList.contains('open') && e.key === 'Escape') {
    closeLogs(); return;
  }
  if (!document.getElementById('configModal').classList.contains('open')) return;
  if (e.key === 'Escape') closeConfig();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveConfig(); }
});

// ── Models manager ────────────────────────────────────────────────────────────
let modelsTokenRequired = false;

function setModelsStatus(msg, cls) {
  const el = document.getElementById('modelsStatus');
  el.textContent = msg;
  el.className = `modal-status ${cls || 'dim'}`;
}

function openModels()  { openModal('modelsModal'); loadModels(); }
function closeModels() { closeModal('modelsModal'); }

let modelsData = null;

async function loadModels() {
  setModelsStatus('loading…', 'dim');
  document.getElementById('modelsList').innerHTML = '<div class="empty-msg">loading…</div>';
  const res = await fetch('/api/models').catch(() => null);
  if (!res) { setModelsStatus('failed to load models', 'err'); return; }
  const d = await res.json();
  modelsData = d;

  modelsTokenRequired = d.token_required;
  const tr = document.getElementById('modelsTokenRow');
  if (d.token_required) {
    tr.style.display = 'flex';
    document.getElementById('modelsToken').value = localStorage.getItem('toolboxToken') || '';
  } else { tr.style.display = 'none'; }

  document.getElementById('modelsSummary').textContent =
    `${d.models.length} models · ${fmtKB(d.total_kb)} · ${d.cache_dir}`;

  if (!d.models.length && !(d.unused_gguf || []).length) {
    document.getElementById('modelsList').innerHTML = '<div class="empty-msg">no cached models</div>';
    document.getElementById('unusedBanner').hidden = true;
    document.getElementById('unusedGgufList').innerHTML = '';
    setModelsStatus('', 'dim'); return;
  }
  renderModels();
  const totalUnused = d.unused_repo_count + d.unused_gguf_count;
  setModelsStatus(`${d.models.length} models · ${d.managed_count} managed · ${fmtKB(d.total_kb)} total`
    + (totalUnused ? ` · ${totalUnused} unused` : ''), 'dim');
}

// Render the repo list + unused banner + unused-GGUF section from the cached data.
function renderModels() {
  const d = modelsData; if (!d) return;
  const onlyUnused = document.getElementById('unusedOnly').checked;

  const totalUnused = d.unused_repo_count + d.unused_gguf_count;
  const banner = document.getElementById('unusedBanner');
  if (totalUnused) {
    banner.hidden = false;
    document.getElementById('unusedBannerText').textContent =
      `⚠ ${totalUnused} model${totalUnused > 1 ? 's' : ''} (${fmtKB(d.unused_repo_kb + d.unused_gguf_kb)}) `
      + `not used by any command or preset`;
  } else {
    banner.hidden = true;
    document.getElementById('unusedOnly').checked = false;
  }

  const rows = d.models.filter(m => !onlyUnused || !m.used);
  const list = document.getElementById('modelsList');
  list.innerHTML = rows.length ? rows.map(m => `
    <div class="model-row ${m.used ? '' : 'is-unused'}" data-repo="${esc(m.repo)}">
      <div class="model-info">
        <div class="model-repo">${esc(m.repo)}</div>
        <div class="model-meta">
          <span class="model-update-badge" data-badge hidden></span>
          ${m.used ? '' : '<span class="model-unused">unused</span>'}
          ${m.linked.length
            ? m.linked.map(l => `<span class="model-link-tag">↳ ~/models/${esc(l)}</span>`).join('')
            : '<span>not linked</span>'}
          ${m.managed ? '' : '<span class="model-unmanaged">unmanaged</span>'}
        </div>
      </div>
      <span class="model-size">${fmtKB(m.size_kb)}</span>
      ${m.used ? ''
        : (m.kind === 'gguf'
            ? `<button class="btn-wire" title="Add a llama.cpp preset for this model" onclick="wirePresetForGguf('${esc(m.gguf_path || '')}','${esc(m.repo)}')">+ preset</button>`
            : `<button class="btn-wire" title="Add a vLLM command that serves this model" onclick="wireCommandForRepo('${esc(m.repo)}')">+ command</button>`)}
      <button class="btn-update" data-update hidden onclick="updateModel('${esc(m.repo)}')">Update</button>
      <button class="btn-drop" onclick="dropModel('${esc(m.repo)}')">Delete</button>
    </div>`).join('') : '<div class="empty-msg">no models match this filter</div>';

  const gwrap = document.getElementById('unusedGgufList');
  const gguf = d.unused_gguf || [];
  gwrap.innerHTML = gguf.length ? '<div class="unused-gguf-head">unused .gguf files — not in any preset or command</div>'
    + gguf.map(g => `
      <div class="model-row is-unused">
        <div class="model-info">
          <div class="model-repo">${esc(g.name)}</div>
          <div class="model-meta">
            <span class="model-unused">unused</span>
            ${g.shards > 1 ? `<span>${g.shards} shards</span>` : ''}
            <span>${esc(g.path)}</span>
          </div>
        </div>
        <span class="model-size">${fmtKB(g.size_kb)}</span>
        <button class="btn-wire" title="Add a llama.cpp preset for this model" onclick="wirePresetForGguf('${esc(g.path)}')">+ preset</button>
      </div>`).join('') : '';
}

// Quick-wire actions: turn an unused model into a command / preset, pre-filled.
function wireCommandForRepo(repo) {
  const cmd = `VLLM_DISABLE_COMPILE_CACHE=1 vllm serve ${repo}`
    + ` --api-key sk-REPLACE_ME --host 0.0.0.0 --port 8081`
    + ` --max-model-len 8192 --gpu-memory-utilization 0.90 --dtype auto`
    + ` --attention-backend TRITON_ATTN --mm-encoder-attn-backend TRITON_ATTN`;
  closeModels();
  openCmdBuilder({ label: `start ${repo}`, cmd, preferMatch: 'vllm' });
}

function wirePresetForGguf(path, repo) {
  const src = path ? path.split('/').pop() : (repo || '').split('/').pop();
  const base = (src || '').replace(/-\d{5}-of-\d{5}\.gguf$/, '').replace(/\.gguf$/, '');
  closeModels();
  openPresetBuilder({ name: base, model: path || '' });
}

async function dropModel(repo) {
  if (!await uiConfirm({
    title: 'Delete cached model?',
    message: `${repo}\n\nRemoves the ~/models symlink and runs 'hf cache rm'. This cannot be undone.`,
    confirmText: 'Delete', danger: true,
  })) return;
  const token = document.getElementById('modelsToken').value;
  if (modelsTokenRequired) localStorage.setItem('toolboxToken', token);
  setModelsStatus(`deleting ${repo}…`, 'dim');
  const res = await fetch('/api/drop-model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': token },
    body: JSON.stringify({ repo }),
  }).catch(() => null);
  if (!res) { setModelsStatus('drop request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setModelsStatus('error: ' + d.error, 'err'); return; }
  // Watch the deletion in the main terminal, then the list can be refreshed.
  closeModels();
  openStream(d.session, `🗑 drop-model ${repo}`);
}

// Read the write token (if required) and persist it for next time.
function modelsToken() {
  const token = document.getElementById('modelsToken').value;
  if (modelsTokenRequired) localStorage.setItem('toolboxToken', token);
  return token;
}

// ── Check for updates (per-row badges) ──────────────────────────────────────────
async function checkUpdates() {
  const btn = document.getElementById('checkUpdatesBtn');
  const label = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> checking…';
  setModelsStatus('checking the Hub for updates…', 'dim');
  const res = await fetch('/api/check-updates', { method: 'POST' }).catch(() => null);
  btn.disabled = false;
  btn.textContent = label;
  if (!res) { setModelsStatus('update check failed', 'err'); return; }
  const d = await res.json();
  applyUpdateBadges(d.results);
  const updatable = Object.values(d.results).filter(r => r.status === 'update').length;
  const unknown   = Object.values(d.results).filter(r => r.status === 'unknown').length;
  const note = unknown ? ` · ${unknown} unknown${d.authenticated ? '' : ' (no HF token)'}` : '';
  setModelsStatus(updatable ? `${updatable} update(s) available${note}` : `all up to date${note}`,
                  updatable ? 'err' : 'ok');
}

function applyUpdateBadges(results) {
  document.querySelectorAll('.model-row').forEach(row => {
    const r = results[row.getAttribute('data-repo')];
    const badge = row.querySelector('[data-badge]');
    const upd   = row.querySelector('[data-update]');
    if (!r || !badge) return;
    badge.hidden = false;
    badge.className = 'model-update-badge ' + r.status;
    if (r.status === 'update')        { badge.textContent = '↑ update available'; if (upd) upd.hidden = false; }
    else if (r.status === 'uptodate') { badge.textContent = '✓ up to date';       if (upd) upd.hidden = true;  }
    else                              { badge.textContent = '? unknown';          if (upd) upd.hidden = true;  }
  });
}

// ── Add / download a new model ──────────────────────────────────────────────────
function toggleAddForm() {
  const f = document.getElementById('addModelForm');
  f.hidden = !f.hidden;
  if (!f.hidden) document.getElementById('amRepo').focus();
}

async function downloadModel() {
  const repo    = document.getElementById('amRepo').value.trim();
  const name    = document.getElementById('amName').value.trim();
  const pattern = document.getElementById('amPattern').value.trim();
  if (!repo) { setModelsStatus('enter a repo id (org/name)', 'err'); document.getElementById('amRepo').focus(); return; }
  setModelsStatus(`starting download of ${repo}…`, 'dim');
  const res = await fetch('/api/download-model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': modelsToken() },
    body: JSON.stringify({ repo, name, pattern }),
  }).catch(() => null);
  if (!res) { setModelsStatus('download request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setModelsStatus('error: ' + d.error, 'err'); return; }
  closeModels();
  openStream(d.session, `⬇ hf-link ${repo}`);
}

// ── Update a single model (re-pull latest revision) ─────────────────────────────
async function updateModel(repo) {
  if (!await uiConfirm({
    title: 'Pull latest revision?',
    message: `${repo}\n\nDownloads any changed files and re-points the ~/models symlink.`,
    confirmText: 'Update',
  })) return;
  setModelsStatus(`updating ${repo}…`, 'dim');
  const res = await fetch('/api/update-model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': modelsToken() },
    body: JSON.stringify({ repo }),
  }).catch(() => null);
  if (!res) { setModelsStatus('update request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setModelsStatus('error: ' + d.error, 'err'); return; }
  closeModels();
  openStream(d.session, `⟳ update ${repo}`);
}

// ── Sync the whole curated list ─────────────────────────────────────────────────
async function syncAll() {
  if (!await uiConfirm({
    title: 'Run sync-models?',
    message: 'Downloads/updates every model in the curated list and refreshes the ~/models symlinks. This can take a while.',
    confirmText: 'Sync all',
  })) return;
  setModelsStatus('starting sync-models…', 'dim');
  const res = await fetch('/api/sync-models', {
    method: 'POST',
    headers: { 'X-Toolbox-Token': modelsToken() },
  }).catch(() => null);
  if (!res) { setModelsStatus('sync request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setModelsStatus('error: ' + d.error, 'err'); return; }
  closeModels();
  openStream(d.session, '⇅ sync-models');
}

// ── Toolbox update manager ──────────────────────────────────────────────────────
let toolboxTokenRequired = false;

function setToolboxStatus(msg, cls) {
  const el = document.getElementById('toolboxStatus');
  el.textContent = msg;
  el.className = `modal-status ${cls || 'dim'}`;
}
function toolboxToken() {
  const token = document.getElementById('toolboxToken').value;
  if (toolboxTokenRequired) localStorage.setItem('toolboxToken', token);
  return token;
}

function openToolboxes()  { openModal('toolboxModal'); loadToolboxRepos(); }
function closeToolboxes() { closeModal('toolboxModal'); }

function tbBadge(r) {
  // Returns {cls, text} for a repo's status object.
  if (r.status === 'update')   return { cls: 'update',   text: `↑ ${r.behind} behind` };
  if (r.status === 'uptodate') return { cls: 'uptodate', text: '✓ up to date' };
  if (r.status === 'missing')  return { cls: 'missing',  text: '✕ repo missing' };
  return { cls: 'unknown', text: '? no upstream' };
}

// Short, human status for a container ("running" / "created" / "exited" / …).
function tbShort(s) {
  s = s || '';
  if (/^up/i.test(s))      return 'running';
  if (/^created/i.test(s)) return 'created';
  if (/^exited/i.test(s))  return 'exited';
  return (s.split(' ')[0] || '').toLowerCase();
}
function tbContainerChip(c) {
  return `<span class="tb-container" data-tip="${esc(c.status)}" data-image="${esc(c.image || '')}">
            <span class="tb-cdot ${c.running ? 'up' : 'down'}"></span>${esc(c.name)}
            <span class="tb-cstatus">${esc(tbShort(c.status))}</span>
            <span class="tb-img-badge" data-img-badge hidden></span>
          </span>`;
}

function renderToolboxRepos(repos, others) {
  const list = document.getElementById('tbRepoList');
  if (!repos.length) { list.innerHTML = '<div class="empty-msg">no toolbox repos configured</div>'; return; }
  let html = repos.map(r => {
    const b = tbBadge(r);
    const cs = (r.containers || []);
    return `
    <div class="tb-repo" data-repo-name="${esc(r.name)}">
      <div class="tb-repo-head">
        <div class="model-info">
          <div class="model-repo">${esc(r.name)}</div>
          <div class="model-meta">
            <span class="model-update-badge ${b.cls}" data-badge>${esc(b.text)}</span>
            <span class="model-branch">${esc(r.branch || '?')} · ${cs.length} toolbox${cs.length === 1 ? '' : 'es'} · ${esc(r.path)}</span>
          </div>
        </div>
        <button class="btn-update" onclick="updateToolbox('${esc(r.name)}')">Update</button>
      </div>
      ${cs.length
        ? `<div class="tb-containers">${cs.map(tbContainerChip).join('')}</div>`
        : `<div class="tb-empty-c">no local toolboxes built from this repo yet</div>`}
    </div>`;
  }).join('');

  if (others && others.length) {
    html += `<div class="tb-others-label">Other toolboxes · not tied to a tracked source</div>
      <div class="tb-repo"><div class="tb-containers">${others.map(tbContainerChip).join('')}</div></div>`;
  }
  list.innerHTML = html;
}

async function loadToolboxRepos() {
  setToolboxStatus('loading…', 'dim');
  document.getElementById('tbRepoList').innerHTML = '<div class="empty-msg">loading…</div>';
  const res = await fetch('/api/toolbox-repos').catch(() => null);
  if (!res) { setToolboxStatus('failed to load repos', 'err'); return; }
  const d = await res.json();

  toolboxTokenRequired = d.token_required;
  const tr = document.getElementById('toolboxTokenRow');
  if (d.token_required) {
    tr.style.display = 'flex';
    document.getElementById('toolboxToken').value = localStorage.getItem('toolboxToken') || '';
  } else { tr.style.display = 'none'; }

  const total = d.repos.reduce((n, r) => n + (r.containers || []).length, 0) + (d.others || []).length;
  document.getElementById('toolboxSummary').textContent =
    `${d.repos.length} source repos · ${total} toolboxes`;
  renderToolboxRepos(d.repos, d.others);
  setToolboxStatus('press “Check updates” to fetch from GitHub', 'dim');
}

function applyToolboxBadges(results) {
  document.querySelectorAll('#tbRepoList .tb-repo[data-repo-name]').forEach(row => {
    const r = results[row.getAttribute('data-repo-name')];
    const badge = row.querySelector('[data-badge]');
    if (!r || !badge) return;
    const b = tbBadge(r);
    badge.className = 'model-update-badge ' + b.cls;
    badge.textContent = b.text;
  });
}

function applyImageBadges(images) {
  images = images || {};
  document.querySelectorAll('#tbRepoList .tb-container[data-image]').forEach(chip => {
    const r = images[chip.getAttribute('data-image')];
    const badge = chip.querySelector('[data-img-badge]');
    if (!badge) return;
    if (r && r.status === 'update') {
      badge.className = 'tb-img-badge update';
      badge.textContent = '⬆ image';
      badge.title = `newer image on registry\nlocal:  ${r.local}\nremote: ${r.remote}`;
      badge.hidden = false;
    } else if (r && r.status === 'uptodate') {
      badge.className = 'tb-img-badge uptodate';
      badge.textContent = '✓ image';
      badge.title = 'image matches registry';
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  });
}

async function checkToolboxUpdates() {
  const btn = document.getElementById('tbCheckBtn');
  const label = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> fetching…';
  setToolboxStatus('git fetch + registry digest check…', 'dim');
  const res = await fetch('/api/toolbox-check-updates', { method: 'POST' }).catch(() => null);
  btn.disabled = false;
  btn.textContent = label;
  if (!res) { setToolboxStatus('update check failed', 'err'); return; }
  const d = await res.json();
  applyToolboxBadges(d.results);
  applyImageBadges(d.images);
  const behind = Object.values(d.results).filter(r => r.status === 'update').length;
  const imgUpd = Object.values(d.images || {}).filter(r => r.status === 'update').length;
  const parts = [];
  if (behind) parts.push(`${behind} repo(s)`);
  if (imgUpd) parts.push(`${imgUpd} image(s)`);
  setToolboxStatus(parts.length ? `updates available: ${parts.join(', ')}` : 'repos & images up to date',
                   parts.length ? 'err' : 'ok');
}

async function updateToolbox(name) {
  if (!await uiConfirm({
    title: 'Update this toolbox source?',
    message: `${name}\n\nRuns 'git pull' then its refresh script (rebuilds/pulls the toolbox images). This can take a while.`,
    confirmText: 'Update',
  })) return;
  setToolboxStatus(`updating ${name}…`, 'dim');
  const res = await fetch('/api/update-toolbox', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': toolboxToken() },
    body: JSON.stringify({ name }),
  }).catch(() => null);
  if (!res) { setToolboxStatus('update request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setToolboxStatus('error: ' + d.error, 'err'); return; }
  closeToolboxes();
  openStream(d.session, `🧰 update ${name}`);
}

async function updateAllToolboxes() {
  if (!await uiConfirm({
    title: 'Update all toolbox sources?',
    message: 'Pulls and refreshes every configured repo in order. This rebuilds/pulls images and can take a long time.',
    confirmText: 'Update all',
  })) return;
  setToolboxStatus('starting full update…', 'dim');
  const res = await fetch('/api/update-toolboxes', {
    method: 'POST',
    headers: { 'X-Toolbox-Token': toolboxToken() },
  }).catch(() => null);
  if (!res) { setToolboxStatus('update request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setToolboxStatus('error: ' + d.error, 'err'); return; }
  closeToolboxes();
  openStream(d.session, '🧰 update all toolboxes');
}

// ── Session log reader ──────────────────────────────────────────────────────────
let logsTokenRequired = false;

function setLogsStatus(msg, cls) {
  const el = document.getElementById('logsStatus');
  el.textContent = msg;
  el.className = `modal-status ${cls || 'dim'}`;
}
function logsToken() {
  const token = document.getElementById('logsToken').value;
  if (logsTokenRequired) localStorage.setItem('toolboxToken', token);
  return token;
}
function openLogs()  { openModal('logsModal'); loadLogs(); }
function closeLogs() { closeModal('logsModal'); }

function fmtBytes(b) {
  if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
  if (b >= 1024)    return (b / 1024).toFixed(0) + ' KB';
  return b + ' B';
}
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60)    return Math.floor(s) + 's ago';
  if (s < 3600)  return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

async function loadLogs() {
  setLogsStatus('loading…', 'dim');
  document.getElementById('logsList').innerHTML = '<div class="empty-msg">loading…</div>';
  const res = await fetch('/api/logs').catch(() => null);
  if (!res) { setLogsStatus('failed to load logs', 'err'); return; }
  const d = await res.json();

  logsTokenRequired = d.token_required;
  const tr = document.getElementById('logsTokenRow');
  if (d.token_required) {
    tr.style.display = 'flex';
    document.getElementById('logsToken').value = localStorage.getItem('toolboxToken') || '';
  } else { tr.style.display = 'none'; }

  const total = d.logs.reduce((n, l) => n + l.size, 0);
  document.getElementById('logsSummary').textContent =
    `${d.logs.length} logs · ${fmtBytes(total)} · ${d.dir}`;

  const list = document.getElementById('logsList');
  if (!d.logs.length) { list.innerHTML = '<div class="empty-msg">no logs on disk</div>'; setLogsStatus('', 'dim'); return; }
  list.innerHTML = d.logs.map(l => `
    <div class="model-row">
      <div class="model-info">
        <div class="model-repo">${esc(l.id)}</div>
        <div class="model-meta">
          ${l.live ? '<span class="model-update-badge live">● live</span>' : ''}
          <span class="model-branch">${fmtBytes(l.size)} · ${ago(l.mtime)}</span>
        </div>
      </div>
      <button class="btn-update" onclick="viewLog('${esc(l.id)}')">View</button>
      <a class="btn-update" href="/api/logs/raw/${encodeURIComponent(l.id)}" download="${esc(l.id)}.log">Download</a>
      <button class="btn-drop" ${l.live ? 'disabled data-tip="kill the session first"' : ''} onclick="deleteLog('${esc(l.id)}')">Delete</button>
    </div>`).join('');

  // Enable "Delete all" only when there's something deletable (live logs are kept).
  const deletable = d.logs.filter(l => !l.live).length;
  const da = document.getElementById('logsDeleteAll');
  da.disabled = deletable === 0;
  da.textContent = deletable ? `🗑 Delete all (${deletable})` : '🗑 Delete all';

  setLogsStatus('newest first · click View to load a log into the terminal', 'dim');
}

async function deleteAllLogs() {
  if (!await uiConfirm({
    title: 'Delete all logs?',
    message: 'Removes every saved session log on disk. Logs of still-running sessions '
      + 'are kept. This only deletes saved output, not anything the sessions did.',
    confirmText: 'Delete all', danger: true,
  })) return;
  setLogsStatus('deleting all…', 'dim');
  const res = await fetch('/api/logs/delete-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': logsToken() },
  }).catch(() => null);
  if (!res) { setLogsStatus('delete request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setLogsStatus('error: ' + d.error, 'err'); return; }
  setLogsStatus(`deleted ${d.deleted} log(s)${d.skipped ? `, kept ${d.skipped} live` : ''}`
    + ` · freed ${fmtBytes(d.freed)}`, 'ok');
  loadLogs();
}

function viewLog(id) {
  closeLogs();
  openStream(id, `📄 log: ${id}`);
}

async function deleteLog(id) {
  if (!await uiConfirm({
    title: 'Delete this log file?',
    message: `${id}.log\n\nThis only removes the saved output, not anything the session did.`,
    confirmText: 'Delete', danger: true,
  })) return;
  setLogsStatus(`deleting ${id}…`, 'dim');
  const res = await fetch('/api/logs/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': logsToken() },
    body: JSON.stringify({ id }),
  }).catch(() => null);
  if (!res) { setLogsStatus('delete request failed', 'err'); return; }
  const d = await res.json();
  if (d.error) { setLogsStatus('error: ' + d.error, 'err'); return; }
  loadLogs();
}

// ── Init ──────────────────────────────────────────────────────────────────────
refreshAll();
