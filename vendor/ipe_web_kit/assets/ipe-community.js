/* ipe_web_kit community — comments · likes · reports widget (Firestore REST, no SDK, no login). OFF unless the site turns it on.
 * Markup comes from ipe_web_kit.community.mount():
 *   <section class="ipe-cm" data-site data-post data-lang data-langs data-project data-key data-features="comments likes reports"
 *            data-hide-at data-gap [data-banned="word|word"]></section>
 * One Firebase project for every ipe web; data per site (see firebase/firestore.rules in the kit repo):
 *   sites/{site}/posts/{post} {count} · sites/{site}/posts/{post}/comments/{id} {name, text, lang, by, createdAt, reports, hidden} · sites/{site}/clients/{token} {lastAt}
 * Moderation: report button (+1; the comment hides itself at hideAt and is no longer served), banned words (kit base + site extra), links refused,
 * minimum gap between posts (rules-enforced per browser token), honeypot field. LINK / BANNED / PAGE / limits mirror ipe_web_kit/community.py — a kit test fails when they drift.
 * Reading the page never depends on this file: every failure ends in a quiet hide or one short line. Text is rendered with textContent only. */
(function () {
  'use strict';
  var PAGE = 20, NAME_MAX = 30, TEXT_MAX = 500;  // keep in sync with ipe_web_kit/community.py
  var LINK = /(https?:|www\.|:\/\/)/i;  // keep in sync with LINK_RE
  var BANNED = /(fuck|shit|bitch|asshole|porn|casino|viagra|씨발|시발|병신|개새끼)/i;  // keep in sync with BANNED_BASE

  // CN·RU: no commenting / liking / reporting (privacy policy table). Keep in sync with ipe_web_kit.privacy (comments_recommended false).
  var BLOCKED_REGIONS = ['CN', 'RU'];
  // Region guess without any network call (best effort, not a legal geo-block — see CHANGELOG 0.3.5): browser time zone, then region subtag of navigator.languages.
  var BLOCKED_ZONES = /^(Asia\/(Shanghai|Chongqing|Chungking|Harbin|Urumqi|Kashgar)|PRC|Europe\/(Moscow|Kaliningrad|Samara|Volgograd|Kirov|Astrakhan|Saratov|Ulyanovsk|Simferopol)|W-SU|Asia\/(Yekaterinburg|Omsk|Novosibirsk|Barnaul|Tomsk|Novokuznetsk|Krasnoyarsk|Irkutsk|Chita|Yakutsk|Khandyga|Vladivostok|Ust-Nera|Magadan|Sakhalin|Srednekolymsk|Kamchatka|Anadyr))$/;
  function regionBlocked() {
    var i, tz = '', langs = [];
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
    if (BLOCKED_ZONES.test(tz)) return true;
    try { langs = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language]).filter(Boolean); } catch (e) {}
    for (i = 0; i < langs.length; i++) {
      var m = /^[a-z]{2,3}(?:-[A-Za-z]{4})?-([A-Za-z]{2})$/i.exec(String(langs[i]));
      if (m && BLOCKED_REGIONS.indexOf(m[1].toUpperCase()) >= 0) return true;
    }
    return false;
  }

  var T = {
    en: { blocked: 'Commenting, liking and reporting are not available in your region. You can still read comments.', like: 'Like', liked: 'Liked', comments: 'Comments', empty: 'No comments yet.', name: 'Nickname', text: 'Write a comment…', send: 'Post', sending: 'Posting…', sent: 'Thanks — your comment is up.', wait: 'Please wait a few seconds before posting again.', nolinks: 'Links are not allowed in comments.', invalid: 'Please add a nickname (up to 30 characters) and a comment (up to 500).', error: 'Could not post right now. Please try again later.', more: 'Show more', unavailable: 'Comments are unavailable right now.', hint: 'No account needed. Your nickname, comment and the time are shown publicly. No links, please.', report: 'Report', reported: 'Reported', banned: 'Please keep comments respectful — some words are not allowed.' },
    ko: { blocked: '이 지역에서는 댓글·좋아요·신고를 이용할 수 없습니다. 기존 댓글은 읽을 수 있습니다.', like: '좋아요', liked: '좋아요 완료', comments: '댓글', empty: '아직 댓글이 없습니다.', name: '닉네임', text: '댓글을 남겨 주세요…', send: '등록', sending: '등록 중…', sent: '감사합니다 — 댓글이 등록되었습니다.', wait: '잠시 후(몇 초 뒤) 다시 등록해 주세요.', nolinks: '댓글에는 링크를 넣을 수 없습니다.', invalid: '닉네임(30자 이내)과 댓글(500자 이내)을 입력해 주세요.', error: '지금은 등록할 수 없습니다. 잠시 후 다시 시도해 주세요.', more: '더 보기', unavailable: '지금은 댓글을 불러올 수 없습니다.', hint: '로그인이 필요 없습니다. 닉네임·댓글·작성 시각이 공개됩니다. 링크는 넣지 말아 주세요.', report: '신고', reported: '신고됨', banned: '부적절한 표현은 사용할 수 없습니다. 내용을 확인해 주세요.' },
    ja: { blocked: 'お住まいの地域ではコメント・いいね・通報はご利用いただけません。既存のコメントは閲覧できます。', like: 'いいね', liked: 'いいね済み', comments: 'コメント', empty: 'まだコメントはありません。', name: 'ニックネーム', text: 'コメントを書く…', send: '投稿', sending: '投稿中…', sent: 'ありがとうございます。コメントを投稿しました。', wait: '少し待ってからもう一度投稿してください。', nolinks: 'コメントにリンクは使えません。', invalid: 'ニックネーム(30文字以内)とコメント(500文字以内)を入力してください。', error: '現在投稿できません。しばらくしてからもう一度お試しください。', more: 'もっと見る', unavailable: '現在コメントを読み込めません。', hint: 'ログイン不要です。ニックネーム・コメント・投稿時刻が公開されます。リンクはご遠慮ください。', report: '報告', reported: '報告済み', banned: '不適切な表現は使えません。内容をご確認ください。' },
    zh: { blocked: '您所在的地区无法使用评论、点赞和举报功能。仍可阅读已有评论。', like: '点赞', liked: '已点赞', comments: '评论', empty: '还没有评论。', name: '昵称', text: '写下你的评论…', send: '发布', sending: '发布中…', sent: '谢谢——评论已发布。', wait: '请稍等几秒再发布。', nolinks: '评论中不允许包含链接。', invalid: '请填写昵称(最多 30 个字符)和评论(最多 500 个字符)。', error: '暂时无法发布,请稍后再试。', more: '显示更多', unavailable: '暂时无法加载评论。', hint: '无需登录。昵称、评论和发布时间将公开显示。请不要放链接。', report: '举报', reported: '已举报', banned: '评论中不允许包含不当用语,请修改后再发布。' },
    es: { blocked: 'Comentar, dar me gusta y denunciar no están disponibles en tu región. Aún puedes leer los comentarios.', like: 'Me gusta', liked: 'Te gusta', comments: 'Comentarios', empty: 'Aún no hay comentarios.', name: 'Apodo', text: 'Escribe un comentario…', send: 'Publicar', sending: 'Publicando…', sent: 'Gracias: tu comentario ya está publicado.', wait: 'Espera unos segundos antes de volver a publicar.', nolinks: 'No se permiten enlaces en los comentarios.', invalid: 'Añade un apodo (máx. 30 caracteres) y un comentario (máx. 500).', error: 'No se pudo publicar ahora. Inténtalo más tarde.', more: 'Ver más', unavailable: 'Los comentarios no están disponibles ahora.', hint: 'No hace falta cuenta. Tu apodo, comentario y la hora se muestran públicamente. Sin enlaces, por favor.', report: 'Denunciar', reported: 'Denunciado', banned: 'Mantén un tono respetuoso: hay palabras que no están permitidas.' },
    fr: { blocked: 'Commenter, aimer et signaler ne sont pas disponibles dans votre région. Vous pouvez toujours lire les commentaires.', like: 'J’aime', liked: 'Aimé', comments: 'Commentaires', empty: 'Aucun commentaire pour l’instant.', name: 'Pseudo', text: 'Écrire un commentaire…', send: 'Publier', sending: 'Publication…', sent: 'Merci — votre commentaire est en ligne.', wait: 'Merci d’attendre quelques secondes avant de republier.', nolinks: 'Les liens ne sont pas autorisés dans les commentaires.', invalid: 'Ajoutez un pseudo (30 caractères max.) et un commentaire (500 max.).', error: 'Publication impossible pour le moment. Réessayez plus tard.', more: 'Voir plus', unavailable: 'Les commentaires sont indisponibles pour le moment.', hint: 'Aucun compte requis. Votre pseudo, votre commentaire et l’heure sont affichés publiquement. Pas de liens, merci.', report: 'Signaler', reported: 'Signalé', banned: 'Merci de rester respectueux : certains mots ne sont pas autorisés.' },
    de: { blocked: 'Kommentieren, Liken und Melden sind in Ihrer Region nicht verfügbar. Kommentare können Sie weiterhin lesen.', like: 'Gefällt mir', liked: 'Gefällt dir', comments: 'Kommentare', empty: 'Noch keine Kommentare.', name: 'Spitzname', text: 'Kommentar schreiben…', send: 'Senden', sending: 'Wird gesendet…', sent: 'Danke – dein Kommentar ist online.', wait: 'Bitte warte ein paar Sekunden, bevor du erneut sendest.', nolinks: 'Links sind in Kommentaren nicht erlaubt.', invalid: 'Bitte gib einen Spitznamen (max. 30 Zeichen) und einen Kommentar (max. 500) ein.', error: 'Senden gerade nicht möglich. Bitte versuche es später erneut.', more: 'Mehr anzeigen', unavailable: 'Kommentare sind gerade nicht verfügbar.', hint: 'Kein Konto nötig. Spitzname, Kommentar und Uhrzeit sind öffentlich sichtbar. Bitte keine Links.', report: 'Melden', reported: 'Gemeldet', banned: 'Bitte bleib respektvoll – manche Wörter sind nicht erlaubt.' },
    pt: { blocked: 'Comentar, curtir e denunciar não estão disponíveis na sua região. Você ainda pode ler os comentários.', like: 'Curtir', liked: 'Curtido', comments: 'Comentários', empty: 'Ainda não há comentários.', name: 'Apelido', text: 'Escreva um comentário…', send: 'Publicar', sending: 'Publicando…', sent: 'Obrigado — seu comentário foi publicado.', wait: 'Aguarde alguns segundos antes de publicar novamente.', nolinks: 'Links não são permitidos nos comentários.', invalid: 'Informe um apelido (até 30 caracteres) e um comentário (até 500).', error: 'Não foi possível publicar agora. Tente novamente mais tarde.', more: 'Ver mais', unavailable: 'Os comentários estão indisponíveis no momento.', hint: 'Não precisa de conta. Seu apelido, comentário e horário ficam públicos. Sem links, por favor.', report: 'Denunciar', reported: 'Denunciado', banned: 'Mantenha o respeito — algumas palavras não são permitidas.' },
    ru: { blocked: 'В вашем регионе комментирование, отметки «Нравится» и жалобы недоступны. Читать комментарии по-прежнему можно.', like: 'Нравится', liked: 'Вам нравится', comments: 'Комментарии', empty: 'Комментариев пока нет.', name: 'Ник', text: 'Напишите комментарий…', send: 'Отправить', sending: 'Отправка…', sent: 'Спасибо — комментарий опубликован.', wait: 'Подождите несколько секунд перед следующей отправкой.', nolinks: 'Ссылки в комментариях не допускаются.', invalid: 'Укажите ник (до 30 символов) и комментарий (до 500).', error: 'Сейчас не удалось отправить. Попробуйте позже.', more: 'Показать ещё', unavailable: 'Комментарии сейчас недоступны.', hint: 'Аккаунт не нужен. Ник, комментарий и время публикуются открыто. Без ссылок, пожалуйста.', report: 'Пожаловаться', reported: 'Жалоба отправлена', banned: 'Пишите уважительно — некоторые слова запрещены.' },
    ar: { blocked: 'التعليق والإعجاب والإبلاغ غير متاحة في منطقتك. لا يزال بإمكانك قراءة التعليقات.', like: 'أعجبني', liked: 'أعجبك', comments: 'التعليقات', empty: 'لا توجد تعليقات بعد.', name: 'الاسم المستعار', text: 'اكتب تعليقًا…', send: 'نشر', sending: 'جارٍ النشر…', sent: 'شكرًا — تم نشر تعليقك.', wait: 'يرجى الانتظار بضع ثوانٍ قبل النشر مرة أخرى.', nolinks: 'الروابط غير مسموحة في التعليقات.', invalid: 'أدخل اسمًا مستعارًا (حتى 30 حرفًا) وتعليقًا (حتى 500 حرف).', error: 'تعذّر النشر الآن. حاول مرة أخرى لاحقًا.', more: 'عرض المزيد', unavailable: 'التعليقات غير متاحة حاليًا.', hint: 'لا حاجة إلى حساب. يظهر الاسم المستعار والتعليق ووقت النشر للجميع. من فضلك بلا روابط.', report: 'إبلاغ', reported: 'تم الإبلاغ', banned: 'يرجى الالتزام بالاحترام — بعض الكلمات غير مسموح بها.' },
    hi: { blocked: 'आपके क्षेत्र में टिप्पणी, पसंद और रिपोर्ट की सुविधा उपलब्ध नहीं है। आप मौजूदा टिप्पणियाँ पढ़ सकते हैं।', like: 'पसंद', liked: 'पसंद किया', comments: 'टिप्पणियाँ', empty: 'अभी कोई टिप्पणी नहीं है।', name: 'उपनाम', text: 'टिप्पणी लिखें…', send: 'भेजें', sending: 'भेजा जा रहा है…', sent: 'धन्यवाद — आपकी टिप्पणी प्रकाशित हो गई।', wait: 'दोबारा भेजने से पहले कुछ सेकंड प्रतीक्षा करें।', nolinks: 'टिप्पणियों में लिंक की अनुमति नहीं है।', invalid: 'उपनाम (अधिकतम 30 अक्षर) और टिप्पणी (अधिकतम 500) लिखें।', error: 'अभी भेजा नहीं जा सका। कृपया बाद में पुनः प्रयास करें।', more: 'और दिखाएँ', unavailable: 'अभी टिप्पणियाँ उपलब्ध नहीं हैं।', hint: 'खाते की ज़रूरत नहीं। उपनाम, टिप्पणी और समय सार्वजनिक रूप से दिखेंगे। कृपया लिंक न डालें।', report: 'रिपोर्ट करें', reported: 'रिपोर्ट किया गया', banned: 'कृपया शालीनता रखें — कुछ शब्दों की अनुमति नहीं है।' },
    id: { blocked: 'Komentar, suka, dan laporan tidak tersedia di wilayah Anda. Anda tetap dapat membaca komentar.', like: 'Suka', liked: 'Disukai', comments: 'Komentar', empty: 'Belum ada komentar.', name: 'Nama panggilan', text: 'Tulis komentar…', send: 'Kirim', sending: 'Mengirim…', sent: 'Terima kasih — komentar Anda sudah tampil.', wait: 'Tunggu beberapa detik sebelum mengirim lagi.', nolinks: 'Tautan tidak diizinkan di komentar.', invalid: 'Isi nama panggilan (maks. 30 karakter) dan komentar (maks. 500).', error: 'Tidak bisa mengirim sekarang. Coba lagi nanti.', more: 'Tampilkan lebih banyak', unavailable: 'Komentar sedang tidak tersedia.', hint: 'Tanpa akun. Nama panggilan, komentar, dan waktu ditampilkan secara publik. Mohon tanpa tautan.', report: 'Laporkan', reported: 'Dilaporkan', banned: 'Mohon tetap sopan — beberapa kata tidak diizinkan.' }
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function store(op, k, v) {
    try { return op === 'get' ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch (e) { return null; }
  }
  function unstore(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function randomId() {
    var a = 'abcdefghijklmnopqrstuvwxyz0123456789', out = '', i;
    try {
      var u = new Uint8Array(20); crypto.getRandomValues(u);
      for (i = 0; i < 20; i++) out += a[u[i] % a.length];
    } catch (e) { for (i = 0; i < 20; i++) out += a[Math.floor(Math.random() * a.length)]; }
    return out;
  }
  function int(v, d) { var n = parseInt(v, 10); return isNaN(n) ? d : n; }
  function words(s) { return String(s || '').split(/\s+/).filter(Boolean); }

  function Community(root) {
    var site = root.getAttribute('data-site'), post = root.getAttribute('data-post');
    var project = root.getAttribute('data-project') || '', key = root.getAttribute('data-key') || '';
    var feats = words(root.getAttribute('data-features'));
    var on = { comments: feats.indexOf('comments') >= 0, likes: feats.indexOf('likes') >= 0, reports: feats.indexOf('reports') >= 0 };
    if (!site || !post || !project || !key || /REPLACE/.test(project + key) || !(on.comments || on.likes)) { root.textContent = ''; return; }  // not configured -> stay empty (hidden by css)
    on.reports = on.reports && on.comments;
    var geoBlocked = regionBlocked();  // CN·RU: read-only — no write UI at all (the Firestore writes are never reachable from the page)
    if (geoBlocked) { on.likes = false; on.reports = false; }
    var langs = words(root.getAttribute('data-langs')).filter(function (l) { return T[l]; });
    if (!langs.length) langs = ['en'];
    var lang = (root.getAttribute('data-lang') || document.documentElement.lang || '').toLowerCase().split('-')[0];
    if (langs.indexOf(lang) < 0) lang = langs.indexOf('en') >= 0 ? 'en' : langs[0];  // the rules accept the site's langs only
    var t = T[lang];
    var hideAt = int(root.getAttribute('data-hide-at'), 3), gapMs = int(root.getAttribute('data-gap'), 30) * 1000;
    var extra = String(root.getAttribute('data-banned') || '').split('|').filter(Boolean)
      .map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); });
    var BANNED_SITE = extra.length ? new RegExp('(' + extra.join('|') + ')', 'i') : null;
    function banned(s) { return BANNED.test(s) || (BANNED_SITE ? BANNED_SITE.test(s) : false); }

    var db = 'projects/' + project + '/databases/(default)/documents';
    var sitePath = '/sites/' + site, postPath = sitePath + '/posts/' + post;
    var base = 'https://firestore.googleapis.com/v1/' + db;
    var q = '?key=' + encodeURIComponent(key);
    var pk = site + ':' + post;
    var likeKey = 'ipe_cm_like:' + pk, lastKey = 'ipe_cm_at:' + site, clientKey = 'ipe_cm_client';
    var client = store('get', clientKey);
    if (!client || !/^[a-z0-9]{20,40}$/.test(client)) { client = randomId(); store('set', clientKey, client); }  // random per-browser token: the post clock in the rules is keyed on it

    function api(method, path, body, extraQ) {
      return fetch(base + path + q + (extraQ || ''), {
        method: method,
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        credentials: 'omit', referrerPolicy: 'strict-origin-when-cross-origin'
      }).then(function (r) {
        if (r.status === 404 && method === 'GET') return null;
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      });
    }

    root.setAttribute('lang', lang);
    root.textContent = '';

    // ---- likes ----
    if (on.likes) {
      var likeRow = el('div', 'ipe-cm__like');
      var likeBtn = el('button', 'ipe-cm__like-btn'); likeBtn.type = 'button';
      var heart = el('span', 'ipe-cm__heart', '♥'); heart.setAttribute('aria-hidden', 'true');
      var likeLabel = el('span', 'ipe-cm__like-label', t.like);
      var likeCount = el('span', 'ipe-cm__like-count', ''); likeCount.setAttribute('aria-live', 'polite');
      likeBtn.appendChild(heart); likeBtn.appendChild(likeLabel);
      likeRow.appendChild(likeBtn); likeRow.appendChild(likeCount);
      root.appendChild(likeRow);
      var count = 0, liked = store('get', likeKey) === '1';
      var paintLike = function () {
        likeBtn.setAttribute('aria-pressed', liked ? 'true' : 'false');
        likeBtn.disabled = liked;
        likeLabel.textContent = liked ? t.liked : t.like;
        likeCount.textContent = count > 0 ? String(count) : '';
      };
      paintLike();
      api('GET', postPath).then(function (d) {
        count = d && d.fields && d.fields.count ? int(d.fields.count.integerValue, 0) : 0;
        paintLike();
      }).catch(function () {});
      likeBtn.addEventListener('click', function () {
        if (liked) return;
        liked = true; count += 1; paintLike();  // optimistic
        store('set', likeKey, '1');
        api('POST', ':commit', { writes: [{  // first like creates {count: 1}; afterwards +1 only (rules)
          update: { name: db + postPath, fields: {} },
          updateMask: { fieldPaths: [] },
          updateTransforms: [{ fieldPath: 'count', increment: { integerValue: '1' } }]
        }] }).catch(function () {
          liked = false; count = Math.max(0, count - 1); paintLike(); unstore(likeKey);
        });
      });
    }

    if (!on.comments) return;

    // ---- comments ----
    var h = el('h2', 'ipe-cm__title', t.comments);
    var list = el('ol', 'ipe-cm__list');
    var status = el('p', 'ipe-cm__status'); status.setAttribute('role', 'status');
    var moreBtn = el('button', 'ipe-cm__more', t.more); moreBtn.type = 'button'; moreBtn.hidden = true;
    var form = el('form', 'ipe-cm__form'); form.setAttribute('novalidate', '');
    var nameIn = el('input', 'ipe-cm__name'); nameIn.type = 'text'; nameIn.maxLength = NAME_MAX; nameIn.placeholder = t.name;
    nameIn.setAttribute('aria-label', t.name); nameIn.autocomplete = 'nickname';
    var textIn = el('textarea', 'ipe-cm__text'); textIn.maxLength = TEXT_MAX; textIn.rows = 3; textIn.placeholder = t.text; textIn.setAttribute('aria-label', t.text);
    var trap = el('input', 'ipe-cm__trap'); trap.type = 'text'; trap.name = 'website'; trap.tabIndex = -1; trap.autocomplete = 'off'; trap.setAttribute('aria-hidden', 'true');
    var send = el('button', 'ipe-cm__send', t.send); send.type = 'submit';
    var hint = el('p', 'ipe-cm__hint', t.hint);
    var formMsg = el('p', 'ipe-cm__msg'); formMsg.setAttribute('role', 'status');
    var row = el('div', 'ipe-cm__row'); row.appendChild(hint); row.appendChild(send);
    form.appendChild(nameIn); form.appendChild(textIn); form.appendChild(trap); form.appendChild(row); form.appendChild(formMsg);
    root.appendChild(h); root.appendChild(list); root.appendChild(status); root.appendChild(moreBtn);
    if (geoBlocked) {  // read-only: the form is never attached, so no submit handler / write path exists for this reader
      var note = el('p', 'ipe-cm__blocked', t.blocked); note.setAttribute('role', 'note'); root.appendChild(note);
    } else root.appendChild(form);

    var cursor = null, fmt;
    try { fmt = new Intl.DateTimeFormat(lang, { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { fmt = null; }
    function docId(doc) { return String(doc.name || '').split('/').pop(); }
    function addComment(doc) {
      var f = doc.fields || {};
      var id = docId(doc), reports = f.reports && f.reports.integerValue ? int(f.reports.integerValue, 0) : 0;
      var li = el('li', 'ipe-cm__item');
      var meta = el('p', 'ipe-cm__meta');
      meta.appendChild(el('strong', 'ipe-cm__by', f.name ? f.name.stringValue : ''));
      var ts = f.createdAt && f.createdAt.timestampValue ? new Date(f.createdAt.timestampValue) : null;
      if (ts && !isNaN(ts) && fmt) { var tm = el('time', 'ipe-cm__time', fmt.format(ts)); tm.setAttribute('datetime', ts.toISOString()); meta.appendChild(tm); }
      var cl = f.lang && f.lang.stringValue;
      if (cl && /^[a-z]{2}$/.test(cl) && langs.length > 1) meta.appendChild(el('span', 'ipe-cm__lang', cl));  // a post's comments are shared by all its language pages
      li.appendChild(meta);
      li.appendChild(el('p', 'ipe-cm__body', f.text ? f.text.stringValue : ''));  // textContent only — never HTML
      if (id && on.reports) {
        var rk = 'ipe_cm_reported:' + pk + ':' + id;
        var done = store('get', rk) === '1';
        var rb = el('button', 'ipe-cm__report', done ? t.reported : t.report);
        rb.type = 'button'; rb.disabled = done;
        rb.addEventListener('click', function () {
          if (rb.disabled) return;
          rb.disabled = true;
          reportComment(id, reports).then(function (hidden) {
            store('set', rk, '1'); rb.textContent = t.reported;
            if (hidden && li.parentNode) { li.parentNode.removeChild(li); if (!list.children.length) status.textContent = t.empty; }
          }).catch(function () { rb.disabled = false; });
        });
        li.appendChild(rb);
      }
      list.appendChild(li);
    }
    // report = +1 on `reports`; the rules require hidden == (reports >= hideAt). A stale count fails the rule once -> re-read and retry.
    function reportComment(id, known) {
      var path = postPath + '/comments/' + id;
      function patch(n) {
        return api('PATCH', path, { fields: { reports: { integerValue: String(n) }, hidden: { booleanValue: n >= hideAt } } },
          '&updateMask.fieldPaths=reports&updateMask.fieldPaths=hidden&currentDocument.exists=true').then(function () { return n >= hideAt; });
      }
      return patch(known + 1).catch(function () {
        return api('GET', path).then(function (d) {
          var cur = d && d.fields && d.fields.reports ? int(d.fields.reports.integerValue, 0) : 0;
          return patch(cur + 1);
        }).catch(function () { return true; });  // gone or already hidden -> treat as done
      });
    }
    function load() {
      moreBtn.disabled = true;
      var sq = {  // hidden comments are never served: the rules only allow queries that filter hidden == false (index: firebase/firestore.indexes.json)
        from: [{ collectionId: 'comments' }],
        where: { fieldFilter: { field: { fieldPath: 'hidden' }, op: 'EQUAL', value: { booleanValue: false } } },
        orderBy: [{ field: { fieldPath: 'createdAt' }, direction: 'ASCENDING' }],
        limit: PAGE + 1
      };
      if (cursor) sq.startAt = { values: [{ timestampValue: cursor }], before: false };
      return api('POST', postPath + ':runQuery', { structuredQuery: sq }).then(function (rows) {
        var docs = (rows || []).filter(function (r) { return r && r.document; }).map(function (r) { return r.document; });
        var more = docs.length > PAGE;
        if (more) docs = docs.slice(0, PAGE);
        docs.forEach(function (x) { addComment(x); });
        var lastDoc = docs.length ? docs[docs.length - 1] : null;
        if (lastDoc && lastDoc.fields && lastDoc.fields.createdAt) cursor = lastDoc.fields.createdAt.timestampValue;
        moreBtn.hidden = !more; moreBtn.disabled = false;
        status.textContent = list.children.length ? '' : t.empty;
      }).catch(function () {
        moreBtn.disabled = false;
        if (!list.children.length) status.textContent = t.unavailable;
      });
    }
    moreBtn.addEventListener('click', load);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      function say(m, bad) { formMsg.textContent = m; formMsg.className = 'ipe-cm__msg' + (bad ? ' ipe-cm__msg--bad' : ''); }
      say('');
      var name = nameIn.value.trim(), text = textIn.value.trim();
      if (trap.value) { say(t.sent); form.reset(); return; }  // honeypot: pretend success, store nothing
      if (!name || name.length > NAME_MAX || !text || text.length > TEXT_MAX) return say(t.invalid, true);
      if (LINK.test(name) || LINK.test(text)) return say(t.nolinks, true);
      if (banned(name) || banned(text)) return say(t.banned, true);
      var last = int(store('get', lastKey) || '0', 0);
      if (Date.now() - last < gapMs) return say(t.wait, true);
      send.disabled = true; send.textContent = t.sending;
      var id = randomId();
      var cpath = db + postPath + '/comments/' + id;
      api('POST', ':commit', { writes: [{
        update: { name: cpath, fields: { name: { stringValue: name }, text: { stringValue: text }, lang: { stringValue: lang }, by: { stringValue: client },
          reports: { integerValue: '0' }, hidden: { booleanValue: false } } },
        updateTransforms: [{ fieldPath: 'createdAt', setToServerValue: 'REQUEST_TIME' }],
        currentDocument: { exists: false }
      }, {  // the same batch stamps this browser's post clock; the rules require it and refuse a second post inside the minimum gap
        update: { name: db + sitePath + '/clients/' + client, fields: {} },
        updateTransforms: [{ fieldPath: 'lastAt', setToServerValue: 'REQUEST_TIME' }]
      }] }).then(function () {
        store('set', lastKey, String(Date.now()));
        addComment({ name: cpath, fields: { name: { stringValue: name }, text: { stringValue: text }, lang: { stringValue: lang }, createdAt: { timestampValue: new Date().toISOString() } } });
        status.textContent = '';
        textIn.value = '';
        say(t.sent);
      }).catch(function () { say(t.error, true); }).then(function () { send.disabled = false; send.textContent = t.send; });
    });

    load();
  }

  function boot() {
    var nodes = document.querySelectorAll('.ipe-cm');
    Array.prototype.forEach.call(nodes, function (root) {
      if (root.getAttribute('data-ipe-cm-init')) return;
      root.setAttribute('data-ipe-cm-init', '1');
      var start = function () { try { Community(root); } catch (e) { root.textContent = ''; } };
      if (window.IntersectionObserver) {  // lazy: only when the reader nears the end of the page
        var io = new IntersectionObserver(function (es) {
          if (es.some(function (x) { return x.isIntersecting; })) { io.disconnect(); start(); }
        }, { rootMargin: '600px 0px' });
        io.observe(root);
      } else start();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
