// Delivery. The form only ever calls submitApplication(formData, { signal }) and awaits
// { ok: true, reference? } or a thrown error carrying .code — so demo mode can be swapped
// for a real endpoint without touching the interface.
import config from './config.js';

export const isDemo = config.mode !== 'endpoint' || !config.endpoint;
export const limits = { maxFileBytes: config.maxFileMB * 1024 * 1024, fileTypes: config.fileTypes };

const fail = (code, fieldErrors) => Object.assign(new Error(code), { code, fieldErrors });

const wait = (ms, signal) => new Promise((resolve, reject) => {
  const t = setTimeout(resolve, ms);
  signal?.addEventListener('abort', () => { clearTimeout(t); reject(fail('timeout')); }, { once: true });
});

export async function submitApplication(formData, { signal } = {}) {
  if (isDemo) {
    // ?demo=fail | slow lets the owner (and e2e.py) see every state. Nothing is sent.
    const hook = new URLSearchParams(location.search).get('demo');
    await wait(hook === 'slow' ? 4000 : 1100, signal);
    if (hook === 'fail') throw fail('network');
    const file = formData.get('cv');
    console.info('[TABOUKHI preview] Nothing was sent.', {
      fields: [...formData.keys()].filter((k) => k !== 'cv'),
      file: file && file.name ? `${file.name} (${file.size} bytes)` : 'none',
    });
    return { ok: true, demo: true };
  }

  let res;
  try {
    res = await fetch(config.endpoint, { method: 'POST', body: formData, signal, headers: { Accept: 'application/json' } });
  } catch (err) {
    throw fail(err?.name === 'AbortError' ? 'timeout' : 'network');
  }
  if (res.status === 413) throw fail('too_large');
  if (res.status === 429) throw fail('rate_limited');
  let data = null;
  try { data = await res.json(); } catch { /* not JSON: treated as a server fault below */ }
  if (res.status === 422 && data?.fieldErrors) throw fail('invalid', data.fieldErrors);
  if (!res.ok || !data?.ok) throw fail('server');
  return { ok: true, reference: typeof data.reference === 'string' ? data.reference : '' };
}
