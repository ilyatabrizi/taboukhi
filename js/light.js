// One light. The hero letters, the O and the footer engraving are all lit by the same
// slanted band; each host turns its own scroll progress into a value 0..1. Nothing loops:
// the frame loop runs only while a value is unsettled, a host is on screen and the tab is
// visible. Reduced motion: the markup's resting state stands and this module does nothing.

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
const ANGLE = 'rotate(32.1 1000 113)';   // the band lies parallel to the A's left leg

export function initLight() {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  let lean = 0;

  const band = (grad) => (v) => grad.setAttribute('gradientTransform', `translate(${lerp(-1300, 1300, v).toFixed(1)} 0) ${ANGLE}`);
  const hosts = [];
  const add = (sel, make) => { const el = document.querySelector(sel); if (el) hosts.push({ el, on: false, cur: null, ...make(el) }); };

  add('[data-light="hero"]', (el) => ({
    target: () => clamp(lerp(0.2, 0.9, clamp(scrollY / (innerHeight * 0.9))) + lean),
    apply: band(el.querySelector('linearGradient')),
  }));
  add('[data-light="ring"]', (el) => ({
    target: () => { const r = el.getBoundingClientRect(); return clamp((innerHeight - r.top) / (innerHeight + r.height)); },
    apply: (v) => el.style.setProperty('--rot', `${lerp(-52, 46, v).toFixed(2)}deg`),
  }));
  add('[data-light="foot"]', (el) => ({
    // Ends with the band resting on the name, not past it.
    target: () => { const r = el.getBoundingClientRect(); return lerp(0, 0.6, clamp((innerHeight - r.top) / (r.height + 120))); },
    apply: band(el.querySelector('linearGradient')),
  }));
  if (!hosts.length) return;

  let raf = 0;
  const frame = () => {
    raf = 0;
    let moving = false;
    for (const h of hosts) {
      if (!h.on) continue;
      const t = h.target();
      if (h.cur === null) h.cur = t;
      const d = t - h.cur;
      if (Math.abs(d) < 0.0005) continue;
      h.cur += d * 0.085;
      h.apply(h.cur);
      moving = true;
    }
    if (moving && !document.hidden) raf = requestAnimationFrame(frame);
  };
  const kick = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(frame); };

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) { const h = hosts.find((x) => x.el === e.target); if (h) h.on = e.isIntersecting; }
    kick();
  }, { rootMargin: '10% 0px' });
  hosts.forEach((h) => io.observe(h.el));

  addEventListener('scroll', kick, { passive: true });
  addEventListener('resize', kick, { passive: true });
  document.addEventListener('visibilitychange', kick);
  if (fine) addEventListener('pointermove', (e) => { lean = (e.clientX / innerWidth - 0.5) * 0.14; kick(); }, { passive: true });
}
