import { initApply } from './apply.js';

window.__tbk = true;

// ── The film. Muted as a property before play() (the attribute alone is not always honoured),
// retried on every signal a strict autoplay policy lifts on, and never left as a silent
// still: if it will not play, the button shows Play.
function initFilm() {
  const v = document.querySelector('[data-film]');
  const btn = document.querySelector('[data-film-toggle]');
  if (!v || !btn) return;
  let wanted = true;
  v.muted = true; v.defaultMuted = true; v.playsInline = true;
  v.setAttribute('muted', ''); v.setAttribute('playsinline', '');

  const show = () => {
    const paused = v.paused;
    btn.setAttribute('aria-pressed', String(paused));
    btn.setAttribute('aria-label', paused ? 'Play the film' : 'Pause the film');
  };
  const play = () => { if (!wanted || document.hidden) return; const p = v.play(); if (p) p.catch(() => show()); };
  v.addEventListener('playing', () => { v.classList.add('is-on'); show(); });
  v.addEventListener('pause', show);
  ['loadedmetadata', 'canplay'].forEach((t) => v.addEventListener(t, play));
  const kick = () => { play(); ['pointerdown', 'touchstart', 'keydown', 'scroll'].forEach((t) => removeEventListener(t, kick)); };
  ['pointerdown', 'touchstart', 'keydown', 'scroll'].forEach((t) => addEventListener(t, kick, { passive: true }));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) play(); });
  btn.addEventListener('click', () => { if (v.paused) { wanted = true; play(); } else { wanted = false; v.pause(); } });
  if (v.readyState >= 2) play();
  play();
}

// ── The scroll edge under the floating controls: on once anything scrolls beneath them.
function initEdge() {
  const edge = document.querySelector('[data-edge]');
  if (!edge) return;
  let queued = false;
  const paint = () => { queued = false; edge.toggleAttribute('data-on', scrollY > 8); };
  addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(paint); } }, { passive: true });
  paint();
}

// ── The glass K catches a light that follows the pointer. Fine pointers only; at rest
// the highlight sits top-left, where the markup puts it.
function initKGlass() {
  const k = document.querySelector('[data-kglass]');
  if (!k || !matchMedia('(hover: hover) and (pointer: fine)').matches || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  let raf = 0, x = 0, y = 0;
  addEventListener('pointermove', (e) => {
    x = e.clientX; y = e.clientY;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const r = k.getBoundingClientRect();
      const mx = Math.min(100, Math.max(0, ((x - r.left) / r.width) * 100));
      const my = Math.min(100, Math.max(0, ((y - r.top) / r.height) * 100));
      k.style.setProperty('--mx', `${(28 + (mx - 28) * 0.5).toFixed(1)}%`);
      k.style.setProperty('--my', `${(18 + (my - 18) * 0.5).toFixed(1)}%`);
    });
  }, { passive: true });
}

// iOS shows :active only when the document listens for touches.
document.addEventListener('touchstart', () => {}, { passive: true });

try { initFilm(); } catch (err) { console.error(err); }
try { initEdge(); } catch (err) { console.error(err); }
try { initKGlass(); } catch (err) { console.error(err); }
try { initApply(); } catch (err) { console.error(err); }
