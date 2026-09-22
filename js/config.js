// The one switch. While mode is 'demo' nothing leaves the browser, the sheet carries its
// preview flag, and index.html keeps <meta name="robots" content="noindex">.
// Going live = mode: 'endpoint' + the URL of the receiver on the house's own host
// (multipart POST, JSON reply { ok: true, reference? }, Access-Control-Allow-Origin on every
// response — the page is cross-origin to it), and removing that meta line.
export default {
  mode: 'demo',            // 'demo' | 'endpoint'
  endpoint: '',
  maxFileMB: 10,           // keep in step with what the host really accepts
  fileTypes: ['pdf', 'doc', 'docx'],
  consentVersion: '2026-09-preview',
  fallbackEmail: '',       // UNKNOWN today; shown after a second failed send once it is set
};
