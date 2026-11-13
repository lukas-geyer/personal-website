(function () {
  const root = document.documentElement;
  const THEMES = ['paper', 'sepia', 'dusk'];
  const LABELS = { paper: 'Paper', sepia: 'Sepia', dusk: 'Dusk' };

  function getSavedTheme() {
    try {
      return localStorage.getItem('site-theme') || 'paper';
    } catch (_) {
      return 'paper';
    }
  }

  function applyTheme(theme) {
    const valid = THEMES.includes(theme) ? theme : 'paper';
    root.setAttribute('data-theme', valid);
    try { localStorage.setItem('site-theme', valid); } catch (_) {}

    const navBtn = document.getElementById('themeCycleBtn');
    if (navBtn) navBtn.textContent = 'Theme: ' + LABELS[valid];

    document.querySelectorAll('[data-set-theme]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.setTheme === valid);
    });
  }

  applyTheme(getSavedTheme());

  const navBtn = document.getElementById('themeCycleBtn');
  if (navBtn) {
    navBtn.addEventListener('click', () => {
      const current = root.getAttribute('data-theme') || 'paper';
      const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      applyTheme(next);
    });
  }

  document.querySelectorAll('[data-set-theme]').forEach((btn) => {
    btn.addEventListener('click', () => applyTheme(btn.dataset.setTheme));
  });

  // Writing Filter Tabs (Home & Writing Index)
  const filterBtns = document.querySelectorAll('.filter-btn');
  const entries = document.querySelectorAll('.writing-entry');
  filterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      filterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const kind = btn.dataset.kind;
      entries.forEach((el) => {
        el.classList.toggle('hidden', kind !== 'all' && el.dataset.kind !== kind);
      });
    });
  });

  // Longform Reader Font Size & Focus Mode
  const prose = document.getElementById('proseBody');
  if (prose) {
    let size = 18;
    try {
      const saved = Number(localStorage.getItem('reader-size'));
      if (saved >= 15 && saved <= 23) size = saved;
    } catch (_) {}
    prose.style.setProperty('--reader-size', size + 'px');

    const dec = document.getElementById('fontDec');
    const inc = document.getElementById('fontInc');
    const updateSize = (delta) => {
      size = Math.min(23, Math.max(15, size + delta));
      prose.style.setProperty('--reader-size', size + 'px');
      try { localStorage.setItem('reader-size', String(size)); } catch (_) {}
    };
    if (dec) dec.addEventListener('click', () => updateSize(-1));
    if (inc) inc.addEventListener('click', () => updateSize(1));

    const focusBtn = document.getElementById('focusToggle');
    if (focusBtn) {
      focusBtn.addEventListener('click', () => {
        const active = document.body.classList.toggle('focus-mode');
        focusBtn.classList.toggle('active', active);
        focusBtn.textContent = active ? 'Focus: On' : 'Focus';
      });
    }

    // Reading progress bar
    const fill = document.getElementById('progressFill');
    if (fill) {
      const updateProgress = () => {
        const rect = prose.getBoundingClientRect();
        const total = Math.max(1, prose.offsetHeight - window.innerHeight * 0.45);
        const passed = Math.max(0, -rect.top + window.innerHeight * 0.25);
        const pct = Math.min(100, Math.max(0, (passed / total) * 100));
        fill.style.width = pct.toFixed(1) + '%';
      };
      window.addEventListener('scroll', updateProgress, { passive: true });
      updateProgress();
    }
  }

  // Semestra Interactive Timetable Shift Schematic
  const shiftBtns = document.querySelectorAll('[data-semestra-state]');
  const schematicSvg = document.getElementById('semestraSchematic');
  if (shiftBtns.length && schematicSvg) {
    const STATES = {
      before: {
        note: 'Initial .ics import · Exam Friday',
        blocks: [
          { x: 44, y: 58, w: 62, h: 24, label: 'Lecture', type: 'fixed' },
          { x: 118, y: 88, w: 62, h: 32, label: 'Study I', type: 'plan' },
          { x: 192, y: 58, w: 62, h: 32, label: 'Study II', type: 'plan' },
          { x: 266, y: 120, w: 62, h: 28, label: 'Review', type: 'plan' },
          { x: 340, y: 58, w: 62, h: 42, label: 'Exam', type: 'exam' }
        ]
      },
      after: {
        note: 'Lecture shifted Wed · Blocks rebalanced',
        blocks: [
          { x: 44, y: 58, w: 62, h: 24, label: 'Lecture', type: 'fixed' },
          { x: 118, y: 88, w: 62, h: 32, label: 'Study I', type: 'plan' },
          { x: 192, y: 58, w: 62, h: 26, label: 'Moved Lab', type: 'fixed' },
          { x: 192, y: 112, w: 62, h: 34, label: 'Study II*', type: 'rebalanced' },
          { x: 266, y: 74, w: 62, h: 44, label: 'Review*', type: 'rebalanced' },
          { x: 340, y: 58, w: 62, h: 42, label: 'Exam', type: 'exam' }
        ]
      }
    };

    const renderState = (key) => {
      const st = STATES[key];
      const noteEl = document.getElementById('schematicNote');
      if (noteEl) noteEl.textContent = st.note;

      const days = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
      let cols = '';
      days.forEach((d, i) => {
        const x = 44 + i * 74;
        cols += `<text x="${x + 31}" y="30" text-anchor="middle" fill="currentColor" fill-opacity="0.45" font-size="9" font-family="ui-monospace, monospace">${d}</text>`;
        cols += `<line x1="${x}" y1="40" x2="${x}" y2="165" stroke="currentColor" stroke-opacity="0.08"/>`;
      });

      let rects = '';
      st.blocks.forEach((b) => {
        const fill =
          b.type === 'exam' ? 'var(--accent)' :
          b.type === 'rebalanced' ? 'var(--app-accent)' :
          b.type === 'plan' ? 'var(--app-accent)' : 'currentColor';
        const fillOp =
          b.type === 'fixed' ? '0.12' :
          b.type === 'plan' ? '0.16' : '0.24';
        const stroke =
          b.type === 'exam' ? 'var(--accent)' :
          b.type === 'fixed' ? 'currentColor' : 'var(--app-accent)';
        const strokeOp = b.type === 'fixed' ? '0.25' : '0.85';
        rects += `<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="3" fill="${fill}" fill-opacity="${fillOp}" stroke="${stroke}" stroke-opacity="${strokeOp}" stroke-width="1"/>`;
        rects += `<text x="${b.x + b.w / 2}" y="${b.y + b.h / 2 + 3}" text-anchor="middle" fill="currentColor" font-size="9" font-family="-apple-system, sans-serif">${b.label}</text>`;
      });

      schematicSvg.innerHTML = `<svg viewBox="0 0 436 180" width="100%" fill="none" xmlns="http://www.w3.org/2000/svg">
        <line x1="36" y1="40" x2="412" y2="40" stroke="currentColor" stroke-opacity="0.14"/>
        ${cols}
        ${rects}
      </svg>`;
    };

    shiftBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        shiftBtns.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        renderState(btn.dataset.semestraState);
      });
    });

    renderState('before');
  }

  // Newsletter Form (handles preview and Netlify AJAX submission cleanly)
  document.querySelectorAll('.newsletter-form').forEach((form) => {
    form.addEventListener('submit', async (e) => {
      const mode = form.dataset.newsletterMode;
      const input = form.querySelector('input[type="email"]');
      const status = form.parentElement.querySelector('.newsletter-status');
      if (!input || !input.value.trim()) return;

      if (mode === 'demo') {
        e.preventDefault();
        if (status) {
          status.textContent = 'Preview confirmation for ' + input.value.trim() + ' — set newsletter.action_url in site.json to connect Buttondown, Kit, or Netlify Forms.';
        }
        input.value = '';
        return;
      }

      if (mode === 'netlify') {
        e.preventDefault();
        if (window.location.protocol === 'about:' || window.location.protocol === 'file:') {
          if (status) {
            status.textContent = 'Preview confirmation for ' + input.value.trim() + ' — live Netlify Forms submission activates once deployed.';
          }
          input.value = '';
          return;
        }
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        try {
          const res = await fetch('/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(new FormData(form)).toString()
          });
          if (!res.ok) throw new Error('Request failed');
          if (status) status.textContent = 'Subscribed — thank you for reading.';
          input.value = '';
        } catch (_) {
          if (status) status.textContent = 'Could not submit right now. Please try again in a moment.';
        } finally {
          if (btn) btn.disabled = false;
        }
      }
    });
  });
})();
