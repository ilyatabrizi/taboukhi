// The application sheet: validation, the link-or-file rule, the file row, a draft that
// survives a reload, and the hand-off to the delivery adapter. Copy that comes back from
// anywhere is set with textContent, never innerHTML.
import config from './config.js';
import { submitApplication, isDemo, limits } from './adapter.js';

const DRAFT_KEY = 'taboukhi.apply.v1';
const DRAFT_FIELDS = ['full_name', 'email', 'phone', 'location', 'discipline', 'current_role', 'portfolio_url', 'message'];
const TYPO = { 'gmial.com': 'gmail.com', 'gmail.con': 'gmail.com', 'gmai.com': 'gmail.com', 'gnail.com': 'gmail.com', 'hotmial.com': 'hotmail.com', 'hotmail.con': 'hotmail.com', 'yahoo.con': 'yahoo.com', 'outlook.con': 'outlook.com', 'icloud.con': 'icloud.com' };

const COPY = {
  name: 'Please enter your name.',
  emailEmpty: 'Please enter your email address.',
  emailBad: 'That email address does not look complete.',
  phone: 'Please check this number, or leave the field empty.',
  discipline: 'Please choose the discipline closest to your work.',
  url: 'This link does not look complete. It should begin with https://',
  pair: 'Add a link or attach a file, so we can see your work.',
  consent: 'Please confirm that we may keep your application in order to consider it.',
  fileType: 'Please choose a PDF or a Word document. Other formats cannot be opened reliably.',
  fileEmpty: 'This file appears to be empty.',
  fileBig: (mb, cap) => `This file is ${mb} MB and the limit is ${cap} MB. A lighter export, or a link, will do.`,
  fileMany: (name) => `One file only. We kept ${name}.`,
  fail: {
    network: 'Your application was not sent. Nothing you entered has been lost. Please try again in a moment.',
    server: 'Your application was not sent. Nothing you entered has been lost. Please try again in a moment.',
    timeout: 'This is taking longer than it should. Nothing has been lost. Please try again, or attach a lighter file.',
    too_large: 'The file was too large to be received. Please attach a lighter file, or share a link instead.',
    rate_limited: 'We have received several attempts from this connection. Please wait a few minutes and try again.',
    invalid: 'Some details need another look. They are marked below.',
    offline: 'You appear to be offline. Your answers are saved on this device. Please send again once you are connected.',
  },
};

const store = {
  read() { try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null'); } catch { return null; } },
  write(v) { try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(v)); } catch { /* private mode: the form works without it */ } },
  clear() { try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* same */ } },
};

const mb = (bytes) => (bytes / 1048576).toFixed(bytes < 1048576 ? 2 : 1).replace(/\.?0+$/, '') || '0';

export function initApply() {
  const form = document.querySelector('[data-form]');
  if (!form) return;
  const $ = (sel, root = form) => root.querySelector(sel);
  const sheet = document.querySelector('[data-sheet]');
  const el = {
    name: $('#f-name'), email: $('#f-email'), phone: $('#f-phone'), disc: $('#f-disc'), url: $('#f-url'),
    cv: $('#f-cv'), msg: $('#f-msg'), consent: $('#f-consent'), hp: $('#f-ref'),
    status: $('[data-status]'), announce: $('[data-announce]'), alert: $('[data-alert]'), submit: $('[data-submit]'), submitLabel: $('[data-submit-label]'),
    drop: $('[data-drop]'), file: $('[data-file]'), fileName: $('[data-file-name]'), fileSize: $('[data-file-size]'),
    fileRemove: $('[data-file-remove]'), fileHelp: $('[data-file-help]'), count: $('[data-count]'), clear: $('[data-clear]'),
    pairErr: $('#pair-err'), letterhead: document.querySelector('[data-letterhead]'),
    done: document.querySelector('[data-done]'),
  };
  let file = null, sending = false, failures = 0, firstTouch = 0;
  const touched = new Set();

  document.querySelectorAll('[data-demo-only]').forEach((n) => { n.hidden = !isDemo; });
  el.fileHelp.textContent = `PDF or Word, up to ${config.maxFileMB} MB.`;

  // ── Messages ───────────────────────────────────────────────────────────────
  // say() is seen and heard; tell() is heard only, so an announcement never moves the sheet
  // under someone's finger.
  const say = (text) => { el.status.textContent = text; };
  const tell = (text) => { el.announce.textContent = text; };
  const fieldOf = (input) => input.closest('.f');
  const errOf = (input) => fieldOf(input).querySelector('.f__err');
  function mark(input, message) {
    const f = fieldOf(input), err = errOf(input);
    f.classList.toggle('is-bad', !!message);
    if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    if (err) err.textContent = message || '';
    return !message;
  }

  // ── Rules ──────────────────────────────────────────────────────────────────
  const rules = {
    full_name: () => { const v = el.name.value.trim(); return v.length >= 2 && /\p{L}/u.test(v) ? '' : COPY.name; },
    email: () => { const v = el.email.value.trim(); if (!v) return COPY.emailEmpty; return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v) ? '' : COPY.emailBad; },
    phone: () => { const v = el.phone.value.trim(); if (!v) return ''; return /^[\d\s+().-]{7,24}$/.test(v) && v.replace(/\D/g, '').length >= 7 ? '' : COPY.phone; },
    discipline: () => (el.disc.value ? '' : COPY.discipline),
    portfolio_url: () => {
      const v = el.url.value.trim(); if (!v) return '';
      try { const u = new URL(v); return /^https?:$/.test(u.protocol) && u.hostname.includes('.') ? '' : COPY.url; } catch { return COPY.url; }
    },
    consent: () => (el.consent.checked ? '' : COPY.consent),
  };
  const inputs = { full_name: el.name, email: el.email, phone: el.phone, discipline: el.disc, portfolio_url: el.url, consent: el.consent };
  const check = (key) => mark(inputs[key], rules[key]());
  // Link or file: one is enough. A link with its own fault reports there, not twice.
  function checkPair(show = true) {
    const urlErr = rules.portfolio_url();
    const ok = !!file || (!!el.url.value.trim() && !urlErr);
    const message = ok || urlErr ? '' : COPY.pair;
    if (show || !message) el.pairErr.textContent = message;
    return !message;
  }

  // ── Draft ──────────────────────────────────────────────────────────────────
  let saveTimer = 0;
  const values = () => Object.fromEntries(DRAFT_FIELDS.map((k) => [k, form.elements[k].value]));
  const save = () => { const v = values(); if (Object.values(v).some(Boolean)) store.write({ v: 1, values: v, hadFile: !!file }); else store.clear(); };
  const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 400); };
  function restore() {
    const d = store.read();
    if (!d || d.v !== 1 || !d.values) return;
    let any = false;
    for (const k of DRAFT_FIELDS) if (typeof d.values[k] === 'string' && d.values[k]) { form.elements[k].value = d.values[k]; any = true; }
    if (any) say(d.hadFile ? 'We kept your draft. Your file could not be kept with it; please attach it again.' : 'We kept your draft.');
  }

  // ── Letterhead: the sheet acknowledges what it has been told ───────────────
  function letterhead(prefix, detail) {
    el.letterhead.textContent = prefix;
    if (!detail) return;
    const dash = document.createElement('span'); dash.className = 'dash'; dash.setAttribute('aria-hidden', 'true');
    el.letterhead.append(dash, document.createTextNode(detail));
  }
  const discName = () => el.disc.selectedOptions[0]?.value ? el.disc.selectedOptions[0].textContent : '';
  const syncDisc = () => { el.disc.classList.toggle('is-empty', !el.disc.value); letterhead('Application', discName()); };

  // ── The file row ───────────────────────────────────────────────────────────
  async function vet(f) {
    if (!f.size) return COPY.fileEmpty;
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (!limits.fileTypes.includes(ext)) return COPY.fileType;
    if (ext === 'pdf') {
      try { const head = new TextDecoder('latin1').decode(await f.slice(0, 1024).arrayBuffer()); if (!head.includes('%PDF-')) return COPY.fileType; } catch { /* unreadable head: let the server decide */ }
    }
    if (f.size > limits.maxFileBytes) return COPY.fileBig(mb(f.size), config.maxFileMB);
    return '';
  }
  function showFile() {
    el.drop.hidden = !!file; el.file.hidden = !file;
    if (file) {
      el.fileName.textContent = file.name; el.fileName.title = file.name;
      el.fileSize.textContent = `${mb(file.size)} MB`;
      el.fileRemove.setAttribute('aria-label', `Remove ${file.name}`);
    }
  }
  async function take(list) {
    const files = [...(list || [])];
    if (!files.length) return;
    let problem = '', kept = null;
    for (const f of files) { const p = await vet(f); if (!p) { kept = f; break; } problem = problem || p; }
    if (!kept) { file = null; el.cv.value = ''; showFile(); mark(el.cv, problem); save(); return; }
    file = kept; mark(el.cv, ''); showFile(); checkPair(false); save();
    tell(files.length > 1 ? COPY.fileMany(kept.name) : `${kept.name}, ${mb(kept.size)} MB, attached.`);
  }
  el.cv.addEventListener('change', () => take(el.cv.files));
  el.fileRemove.addEventListener('click', () => { file = null; el.cv.value = ''; showFile(); save(); tell('File removed.'); el.cv.focus(); });
  if (matchMedia('(hover: hover) and (pointer: fine)').matches) {
    const zone = el.drop.closest('.f');
    ['dragenter', 'dragover'].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); el.drop.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach((t) => zone.addEventListener(t, () => el.drop.classList.remove('is-over')));
    zone.addEventListener('drop', (e) => { e.preventDefault(); take(e.dataTransfer?.files); });
    // A file that misses the row must not navigate the tab away and take the form with it.
    ['dragover', 'drop'].forEach((t) => addEventListener(t, (e) => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); }));
  }

  // ── Field behaviour ────────────────────────────────────────────────────────
  form.addEventListener('focusin', () => { if (!firstTouch) firstTouch = performance.now(); }, { once: true });
  for (const [key, input] of Object.entries(inputs)) {
    input.addEventListener('blur', () => { touched.add(key); check(key); if (key === 'portfolio_url' && touched.has('cv')) checkPair(false); });
    input.addEventListener(input.type === 'checkbox' || input.tagName === 'SELECT' ? 'change' : 'input', () => {
      if (fieldOf(input).classList.contains('is-bad')) check(key);
      if (key === 'portfolio_url' && el.pairErr.textContent) checkPair(false);
    });
  }
  el.cv.addEventListener('blur', () => touched.add('cv'));
  el.url.addEventListener('blur', () => { const v = el.url.value.trim(); if (v && !/^[a-z][a-z\d+.-]*:/i.test(v)) { el.url.value = `https://${v}`; check('portfolio_url'); } });
  el.email.addEventListener('blur', () => {
    const [user, domain] = el.email.value.trim().split('@');
    const fix = domain && TYPO[domain.toLowerCase()];
    if (!fix || rules.email()) return;
    const err = errOf(el.email); const b = document.createElement('button');
    b.type = 'button'; b.className = 'textbtn'; b.textContent = `Did you mean ${user}@${fix}?`;
    b.addEventListener('click', () => { el.email.value = `${user}@${fix}`; err.textContent = ''; saveSoon(); el.email.focus(); });
    err.textContent = ''; err.append(b);
  });
  el.disc.addEventListener('change', syncDisc);
  el.msg.addEventListener('input', () => {
    const left = el.msg.maxLength - el.msg.value.length;
    el.count.hidden = left > 300; el.count.textContent = `${left} characters remaining`;
    el.msg.style.height = 'auto'; el.msg.style.height = `${Math.min(el.msg.scrollHeight + 2, 420)}px`;
  });
  form.addEventListener('input', saveSoon);
  form.addEventListener('change', saveSoon);
  addEventListener('pagehide', save);
  document.addEventListener('visibilitychange', () => { if (document.hidden) save(); });

  // A discipline row writes itself into the letter. Focus is left alone, so a phone
  // keyboard does not leap up mid-scroll.
  document.querySelectorAll('[data-discipline]').forEach((row) => row.addEventListener('click', () => {
    if (sending || !form.isConnected || form.hidden) return;
    el.disc.value = row.dataset.discipline; syncDisc(); mark(el.disc, ''); save();
  }));

  // Clear: asks once, inline.
  let armed = 0;
  el.clear.addEventListener('click', () => {
    if (!armed) { el.clear.textContent = 'Clear everything? Press again to confirm'; armed = setTimeout(() => { armed = 0; el.clear.textContent = 'Clear the form'; }, 5000); return; }
    clearTimeout(armed); armed = 0; el.clear.textContent = 'Clear the form';
    form.reset(); file = null; showFile(); store.clear(); syncDisc(); el.pairErr.textContent = ''; el.alert.textContent = '';
    Object.values(inputs).concat(el.cv).forEach((i) => mark(i, '')); say('The form has been cleared.');
  });

  // ── Send ───────────────────────────────────────────────────────────────────
  function busy(on) {
    sending = on;
    form.setAttribute('aria-busy', String(on));
    form.querySelectorAll('fieldset').forEach((fs) => { fs.inert = on; });
    el.submit.setAttribute('aria-disabled', String(on));
    el.submitLabel.textContent = on ? 'Sending your application' : 'Send application';
  }
  function finish(result) {
    const first = el.name.value.trim().split(/\s+/)[0];
    sheet.style.minHeight = `${sheet.offsetHeight}px`;
    document.querySelector('[data-done-email]').textContent = el.email.value.trim();
    const ref = document.querySelector('[data-done-ref]');
    if (result.reference) { ref.textContent = `Reference ${result.reference}`; ref.hidden = false; }
    letterhead(`From ${first}`, discName());
    form.hidden = true; sheet.querySelector('.sheet__flag').hidden = true;
    el.done.hidden = false; el.done.setAttribute('data-in', '');
    store.clear();
    const title = document.querySelector('[data-done-title]');
    title.focus({ preventScroll: true });
    sheet.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    requestAnimationFrame(() => setTimeout(() => { sheet.style.minHeight = ''; }, 600));
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (sending) return;
    el.alert.textContent = '';
    const invalid = Object.keys(inputs).filter((k) => !check(k)).map((k) => inputs[k]);
    if (!checkPair(true)) invalid.push(el.url);
    if (invalid.length) {
      say(invalid.length === 1 ? 'One field needs your attention.' : `${invalid.length} fields need your attention.`);
      [el.name, el.email, el.phone, el.disc, el.url, el.consent].find((i) => invalid.includes(i)).focus();
      return;
    }
    if (el.hp.value && isDemo) { finish({ ok: true }); return; }   // live mode still posts, flagged, and the server quarantines
    if (navigator.onLine === false || new URLSearchParams(location.search).get('demo') === 'offline') { el.alert.textContent = COPY.fail.offline; return; }

    const data = new FormData();
    for (const k of DRAFT_FIELDS) data.set(k, form.elements[k].value.trim());
    if (file) data.set('cv', file, file.name);
    data.set('consent', 'true');
    data.set('consent_version', config.consentVersion);
    data.set('meta', JSON.stringify({ elapsed_ms: firstTouch ? Math.round(performance.now() - firstTouch) : 0, hp: !!el.hp.value }));

    busy(true); say(''); tell('Sending your application.');
    const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), 45000);
    try {
      const result = await submitApplication(data, { signal: ctl.signal });
      busy(false); tell(''); finish(result);
    } catch (err) {
      busy(false); tell(''); failures += 1;
      let text = COPY.fail[err?.code] || COPY.fail.network;
      if (failures > 1 && config.fallbackEmail) text += ` If this continues, write to us at ${config.fallbackEmail}.`;
      el.alert.textContent = text;
      if (err?.code === 'invalid' && err.fieldErrors) for (const [k, m] of Object.entries(err.fieldErrors)) if (inputs[k]) mark(inputs[k], String(m));
      el.submit.focus();
    } finally { clearTimeout(timer); }
  });

  addEventListener('offline', () => { if (Object.values(values()).some(Boolean)) say('You appear to be offline. Your answers are saved on this device.'); });
  addEventListener('online', () => { if (el.status.textContent.startsWith('You appear')) say('You are connected again.'); });

  restore(); syncDisc(); showFile();
}
