(function () {
  'use strict';
  // language selector -> language page (static /<lang>/ addresses)
  var sel = document.getElementById('lang');
  if (sel) {
    sel.addEventListener('change', function () {
      try { localStorage.setItem('draft_lang', this.value); } catch (e) {}
      var path = this.getAttribute('data-path') || '';
      location.href = (this.value === 'en' && !path) ? '/' : '/' + this.value + '/' + path;
    });
  }
  // an explicit language link click is a choice too (otherwise the root would send the visitor straight back)
  document.querySelectorAll('.foot-langs a[hreflang]').forEach(function (a) {
    a.addEventListener('click', function () {
      try { localStorage.setItem('draft_lang', a.getAttribute('hreflang')); } catch (e) {}
    });
  });
  // root only: small dismissible "view in <language>" hint when the browser language is supported (never auto-redirects)
  var hint = document.getElementById('langhint');
  if (hint) {
    try {
      var map = JSON.parse(hint.getAttribute('data-langs') || '{}');
      var closed = false;
      try { closed = localStorage.getItem('draft_hint_closed') === '1'; } catch (e) {}
      var prefs = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language || ''];
      var first = String(prefs[0] || '').toLowerCase().split('-')[0];
      if (!closed && map[first]) {
        var a = document.createElement('a');
        a.href = '/' + first + '/';
        a.setAttribute('hreflang', first);
        a.setAttribute('lang', first);
        a.textContent = map[first][0];
        a.addEventListener('click', function () {
          try { localStorage.setItem('draft_lang', first); } catch (e) {}
        });
        var x = document.createElement('button');
        x.type = 'button';
        x.setAttribute('aria-label', map[first][1]);
        x.textContent = '\u00d7';
        x.addEventListener('click', function () {
          hint.hidden = true;
          try { localStorage.setItem('draft_hint_closed', '1'); } catch (e) {}
        });
        hint.className = 'langhint';
        hint.setAttribute('role', 'note');
        hint.appendChild(a);
        hint.appendChild(x);
        hint.hidden = false;
      }
    } catch (e) {}
  }
  // blog: example-message cards get a copy button
  var prose = document.querySelector('.prose[data-copy]');
  if (prose && navigator.clipboard) {
    prose.querySelectorAll('blockquote').forEach(function (bq) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'copy-btn';
      b.setAttribute('aria-label', prose.getAttribute('data-copy'));
      b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><span class="copy-msg" role="status"></span>';
      b.addEventListener('click', function () {
        navigator.clipboard.writeText(bq.innerText.trim()).then(function () {
          b.classList.add('done');
          b.querySelector('.copy-msg').textContent = prose.getAttribute('data-copied');
          setTimeout(function () { b.classList.remove('done'); b.querySelector('.copy-msg').textContent = ''; }, 1800);
        }, function () {});
      });
      bq.appendChild(b);
    });
  }
  // scroll reveal
  var els = document.querySelectorAll('.reveal:not(.in)');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.16 });
    els.forEach(function (el) { io.observe(el); });
  } else {
    els.forEach(function (el) { el.classList.add('in'); });
  }
  // hero: raw speech types out, then becomes the clean paragraph
  var rawEl = document.getElementById('demoRaw');
  var demo = document.getElementById('heroDemo');
  if (rawEl && demo) {
    var rawText = rawEl.getAttribute('data-raw') || '';
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      demo.classList.add('done');
    } else {
      var i = 0;
      var type = function () {
        if (i <= rawText.length) {
          rawEl.textContent = rawText.slice(0, i);
          i++;
          setTimeout(type, 34);
        } else {
          setTimeout(function () { demo.classList.add('done'); }, 900);
        }
      };
      setTimeout(type, 1400);
    }
  }
})();
