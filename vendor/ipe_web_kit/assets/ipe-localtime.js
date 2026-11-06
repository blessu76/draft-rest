/* ipe-localtime v2 · 정본 ipe-rest/shared/ipe-localtime.js · 사본은 바이트 그대로 */
/* time[data-ipe-time] 의 datetime(+09:00)을 보는 기기 시간대로 바꿔 보인다. 실패하면 정적 KST 글자를 그대로 둔다. */
/* v2: 오프셋 없는/잘못된 datetime 은 건너뜀 · 그레고리력·라틴 숫자 고정 */
(function () {
  try {
    var zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    var names = { 'Asia/Seoul': 'KST', 'Asia/Tokyo': 'JST' };
    var ok = /^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?([+-]\d\d:?\d\d|Z)$/;
    var fmt = new Intl.DateTimeFormat(document.documentElement.lang || 'en', {
      calendar: 'gregory', numberingSystem: 'latn',
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'
    });
    var els = document.querySelectorAll('time[data-ipe-time]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      try {
        if (el.hasAttribute('data-ipe-time-done')) continue;
        var raw = (el.getAttribute('datetime') || '').trim();
        if (!ok.test(raw)) continue;
        var d = new Date(raw.replace(/([+-]\d\d)(\d\d)$/, '$1:$2'));
        if (isNaN(d.getTime())) continue;
        var text = fmt.formatToParts(d).map(function (p) {
          return p.type === 'timeZoneName' && names[zone] ? names[zone] : p.value;
        }).join('');
        if (!el.getAttribute('title')) el.setAttribute('title', el.textContent.trim());
        el.textContent = text;
        el.setAttribute('data-ipe-time-done', '');
      } catch (e) {}
    }
  } catch (e) {}
})();
