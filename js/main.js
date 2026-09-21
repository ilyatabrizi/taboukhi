import { initLight } from './light.js';
import { initApply } from './apply.js';

window.__tbk = true;   // tells the inline guard in <head> that the reveals have an owner

// ── Masthead: backed by whichever ground lies under it, clear over the hero, away while the
// reader moves down and back on the way up. Recomputed on load, hash and resize as well as
// scroll — a deep link to #apply must be right without anyone scrolling.
function initMast() {
  const mast = document.querySelector('[data-mast]');
  if (!mast) return;
  const grounds = [...document.querySelectorAll('main > [data-ground], footer[data-ground]')];
  const heroMark = document.querySelector('.hero__mark');
  let queued = false, lastY = scrollY;

  const paint = () => {
    queued = false;
    const h = mast.offsetHeight, y = scrollY;
    let on = 'onyx';
    for (const el of grounds) { const b = el.getBoundingClientRect(); if (b.top <= h / 2 && b.bottom > h / 2) on = el.dataset.ground; }
    if (mast.dataset.on !== on) mast.dataset.on = on;
    mast.toggleAttribute('data-docked', !!heroMark && heroMark.getBoundingClientRect().bottom < h);
    if (y < h * 2 || y < lastY - 6) mast.removeAttribute('data-away');
    else if (y > lastY + 6) mast.setAttribute('data-away', '');
    if (Math.abs(y - lastY) > 6) lastY = y;
  };
  const ask = () => { if (!queued) { queued = true; requestAnimationFrame(paint); } };

  paint();
  addEventListener('scroll', ask, { passive: true });
  addEventListener('resize', ask, { passive: true });
  addEventListener('hashchange', ask);
  addEventListener('load', ask);
  document.fonts?.ready.then(ask);
}

// ── Arrivals. CSS hides [data-reveal] only under .js, so without this file — or without
// IntersectionObserver — everything simply stands where it is.
function initReveals() {
  const els = [...document.querySelectorAll('[data-reveal]')];
  if (!('IntersectionObserver' in window)) { els.forEach((el) => el.classList.add('is-in')); return; }
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  els.forEach((el) => io.observe(el));
}

try { initMast(); } catch (err) { console.error(err); }
try { initReveals(); } catch (err) { document.documentElement.classList.remove('js'); console.error(err); }
try { initLight(); } catch (err) { console.error(err); }
try { initApply(); } catch (err) { console.error(err); }
