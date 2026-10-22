(function () {
  'use strict';
  // language selector -> language page (static /<lang>/ addresses)
  var sel = document.getElementById('lang');
  if (sel) {
    sel.addEventListener('change', function () {
      try { localStorage.setItem('draft_lang', this.value); } catch (e) {}
      location.href = '/' + this.value + '/';
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
