// Community features, loaded only when hugo.toml sets params.communityAPI (layouts/_default/baseof.html).
// Talks to the community API in server/. Everything people write is shown with textContent, never as HTML.
//
//   header       the account button (sign in / your name)
//   Happening    Interested / Going / "Find someone to go with" on every event card, and the digest form
//   /account/    sign in by email link, profile, going-together requests, my events, data export and deletion
//   /noticeboard/ Wish Wall, achievements and opportunities
//   /suggest/    suggest an event
//   /moderate/   the moderation queue, numbers and roles
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="hellotas-api"]');
  var stringsEl = document.getElementById('cm-strings');
  if (!meta || !stringsEl) return;
  var API = meta.content.replace(/\/+$/, '');
  var S = JSON.parse(stringsEl.textContent);
  var LANG = S.lang || 'en';
  var LOCALE = { en: 'en-AU', zh: 'zh-CN', ne: 'ne-NP-u-nu-latn' }[LANG] || 'en-AU';
  var TOKEN = 'hellotas.session';
  var RETURN = 'hellotas.return';
  var me = null;

  // -- small helpers ---------------------------------------------------------------------------------------------
  function store(key, value) {
    try {
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { /* storage blocked: the session lasts for this page only */ }
  }
  function stored(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  function t(key, values) {
    var s = S[key] || key;
    Object.keys(values || {}).forEach(function (k) { s = s.split('{' + k + '}').join(values[k]); });
    return s;
  }

  // h('button', {class: 'x', onclick: fn}, ['text', otherNode]); strings always become text nodes
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'text') el.textContent = v;
      else el.setAttribute(k, v === true ? '' : v);
    });
    [].concat(children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    });
    return el;
  }

  function api(method, path, body) {
    var headers = { 'Accept': 'application/json' };
    var token = stored(TOKEN);
    if (token) headers.Authorization = 'Bearer ' + token;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(API + path, { method: method, headers: headers, body: body === undefined ? undefined : JSON.stringify(body) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (r.status === 401 && token) { store(TOKEN, null); me = null; }
          if (!r.ok) {
            var err = new Error(typeof data.detail === 'string' ? data.detail : S.cmError);
            err.status = r.status;
            throw err;
          }
          return data;
        });
      }, function () { throw new Error(S.cmError); });
  }

  function formatDate(iso, withTime) {
    try {
      var opts = { timeZone: 'Australia/Hobart', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' };
      if (withTime) { opts.hour = 'numeric'; opts.minute = '2-digit'; }
      return new Intl.DateTimeFormat(LOCALE, opts).format(new Date(iso));
    } catch (e) { return iso; }
  }

  function message(el, text, kind) {
    el.textContent = text || '';
    el.className = 'cm-message' + (kind ? ' cm-message--' + kind : '');
    el.hidden = !text;
  }

  function busy(button, on) {
    button.disabled = on;
    button.setAttribute('aria-busy', on ? 'true' : 'false');
  }

  // Send people to the account page to sign in, and bring them back here afterwards
  function goSignIn() {
    store(RETURN, JSON.stringify({ url: location.href, at: Date.now() }));
    location.href = S.account;
  }

  function signInPrompt() {
    return h('p', { class: 'cm-note' }, [
      S.cmSignInToUse + ' ',
      h('a', { href: S.account, onclick: function (e) { e.preventDefault(); goSignIn(); } }, S.cmSignIn + ' →')
    ]);
  }

  // The account links in the ☰ menu and the footer: the person's name when signed in
  function updateAccountButton() {
    document.querySelectorAll('[data-cm-account-label]').forEach(function (label) {
      label.textContent = me ? me.display_name : S.cmSignIn;
    });
  }

  // -- Happening: interested / going / buddies ---------------------------------------------------------------------
  var stats = {};

  function renderBars(id) {
    var s = stats[id] || { interested: 0, going: 0, buddies: 0 };
    document.querySelectorAll('[data-cm-event="' + id + '"]').forEach(function (bar) {
      bar.querySelectorAll('[data-cm-mark]').forEach(function (b) {
        b.setAttribute('aria-pressed', s.mine === b.getAttribute('data-cm-mark') ? 'true' : 'false');
      });
      var parts = [];
      if (s.going) parts.push(t('cmCountGoing', { n: s.going }));
      if (s.interested) parts.push(t('cmCountInterested', { n: s.interested }));
      if (s.buddies) parts.push(t('cmBuddyCount', { n: s.buddies }));
      var counts = bar.querySelector('[data-cm-counts]');
      counts.textContent = parts.join(' · ');
      counts.hidden = !parts.length;
    });
  }

  function eventBars() {
    var cards = document.querySelectorAll('.hp-card[data-event]');
    if (!cards.length) return;
    var ids = [];
    cards.forEach(function (card) {
      var id = card.getAttribute('data-event');
      if (ids.indexOf(id) < 0) ids.push(id);
      if (card.querySelector('.cm-event')) return;
      var body = card.querySelector('.hp-card-body');
      if (!body) return;
      body.appendChild(h('div', { class: 'cm-event', 'data-cm-event': id }, [
        h('div', { class: 'cm-event-buttons' }, [
          h('button', { type: 'button', class: 'cm-chip', 'data-cm-mark': 'interested', 'aria-pressed': 'false' }, S.cmInterested),
          h('button', { type: 'button', class: 'cm-chip', 'data-cm-mark': 'going', 'aria-pressed': 'false' }, S.cmGoing),
          h('button', { type: 'button', class: 'cm-chip cm-chip--buddy', 'data-cm-buddies': '' }, S.cmFindBuddy)
        ]),
        h('p', { class: 'cm-event-counts', 'data-cm-counts': '', hidden: true })
      ]));
    });
    api('GET', '/v1/events/stats?ids=' + encodeURIComponent(ids.join(','))).then(function (data) {
      stats = data.events || {};
      ids.forEach(renderBars);
    }, function () { /* counts are a nicety; the buttons still work */ });

    document.addEventListener('click', function (e) {
      var markButton = e.target.closest('[data-cm-mark]');
      var buddyButton = e.target.closest('[data-cm-buddies]');
      var bar = e.target.closest('[data-cm-event]');
      if (!bar || (!markButton && !buddyButton)) return;
      var id = bar.getAttribute('data-cm-event');
      if (!me) { goSignIn(); return; }
      if (markButton) {
        var wanted = markButton.getAttribute('data-cm-mark');
        var status = (stats[id] && stats[id].mine === wanted) ? 'none' : wanted;
        busy(markButton, true);
        api('PUT', '/v1/events/' + id + '/mark', { status: status }).then(function (s) {
          stats[id] = s;
          renderBars(id);
        }).catch(function (err) { alert(err.message); }).then(function () { busy(markButton, false); });
      } else {
        var card = bar.closest('.hp-card');
        var title = card && card.querySelector('.hp-card-title');
        openBuddies(id, title ? title.textContent : '');
      }
    });
  }

  var dialog = null;
  function openBuddies(id, title) {
    if (!dialog) {
      dialog = h('dialog', { class: 'cm-dialog', 'aria-labelledby': 'cm-dialog-title' });
      document.body.appendChild(dialog);
      dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
    }
    dialog.textContent = '';
    var list = h('div', { class: 'cm-buddy-list' }, h('p', { class: 'cm-note' }, S.cmLoading));
    var note = h('textarea', { id: 'cm-buddy-note', rows: '2', maxlength: '280', placeholder: S.cmBuddyNotePlaceholder });
    var status = h('p', { class: 'cm-message', hidden: true, role: 'status' });
    var save = h('button', { type: 'button', class: 'btn-primary' }, S.cmBuddyListMe);
    var remove = h('button', { type: 'button', class: 'hp-btn-outline', hidden: true }, S.cmBuddyRemove);
    dialog.appendChild(h('div', { class: 'cm-dialog-card' }, [
      h('button', { type: 'button', class: 'cm-dialog-close', 'aria-label': S.cmClose, onclick: function () { dialog.close(); } }, '×'),
      h('h2', { id: 'cm-dialog-title', class: 'cm-dialog-title' }, S.cmBuddyTitle),
      h('p', { class: 'cm-dialog-event' }, title),
      h('p', { class: 'cm-note' }, S.cmBuddyIntro),
      list,
      h('div', { class: 'cm-buddy-me' }, [
        h('label', { for: 'cm-buddy-note' }, S.cmBuddyNoteLabel), note,
        h('div', { class: 'cm-actions' }, [save, remove]), status
      ])
    ]));

    function draw(buddies) {
      list.textContent = '';
      var mine = buddies.filter(function (b) { return b.mine; })[0];
      if (mine) { note.value = mine.note; save.textContent = S.cmBuddyUpdate; remove.hidden = false; }
      else { save.textContent = S.cmBuddyListMe; remove.hidden = true; }
      var others = buddies.filter(function (b) { return !b.mine; });
      if (!others.length) { list.appendChild(h('p', { class: 'cm-empty' }, S.cmBuddyEmpty)); }
      others.forEach(function (b) {
        var details = [b.course, b.languages].filter(Boolean).join(' · ');
        var askBox = h('input', { type: 'text', maxlength: '280', placeholder: S.cmBuddyAskMessage, 'aria-label': S.cmBuddyAskMessage });
        var ask = h('button', { type: 'button', class: 'hp-btn-outline' }, S.cmBuddyAsk);
        var state = { pending: S.cmBuddyAsked, accepted: S.cmBuddyAccepted, declined: S.cmBuddyDeclined }[b.asked];
        ask.addEventListener('click', function () {
          busy(ask, true);
          api('POST', '/v1/events/' + id + '/buddies/' + b.id + '/ask', { message: askBox.value }).then(function () {
            ask.replaceWith(h('span', { class: 'cm-tag' }, S.cmBuddyAsked));
            askBox.remove();
          }, function (err) { busy(ask, false); alert(err.message); });
        });
        list.appendChild(h('div', { class: 'cm-buddy' }, [
          h('p', { class: 'cm-buddy-name' }, b.name),
          details ? h('p', { class: 'cm-buddy-meta' }, details) : null,
          b.note ? h('p', { class: 'cm-buddy-note' }, '“' + b.note + '”') : null,
          state ? h('span', { class: 'cm-tag' }, state) : h('div', { class: 'cm-buddy-ask' }, [askBox, ask])
        ]));
      });
    }
    function load() {
      return api('GET', '/v1/events/' + id + '/buddies').then(function (d) { draw(d.buddies); },
        function (err) { list.textContent = ''; list.appendChild(h('p', { class: 'cm-message cm-message--error' }, err.message)); });
    }
    save.addEventListener('click', function () {
      busy(save, true);
      api('PUT', '/v1/events/' + id + '/buddy', { note: note.value }).then(function (d) {
        draw(d.buddies);
        message(status, S.cmSaved, 'ok');
        refreshStats(id);
      }, function (err) { message(status, err.message, 'error'); }).then(function () { busy(save, false); });
    });
    remove.addEventListener('click', function () {
      api('DELETE', '/v1/events/' + id + '/buddy').then(function () { note.value = ''; load(); refreshStats(id); });
    });
    load();
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
  }

  function refreshStats(id) {
    api('GET', '/v1/events/stats?ids=' + id).then(function (d) { stats[id] = d.events[id]; renderBars(id); });
  }

  // -- the digest form (Happening page) -------------------------------------------------------------------------
  function digestForm() {
    var form = document.querySelector('[data-cm-digest]');
    if (!form) return;
    form.hidden = false;
    var status = form.querySelector('[data-cm-digest-status]');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var button = form.querySelector('button[type="submit"]');
      var topics = Array.prototype.map.call(form.querySelectorAll('input[name="topic"]:checked'), function (i) { return i.value; });
      busy(button, true);
      api('POST', '/v1/digest/subscribe', { email: form.email.value, lang: LANG, topics: topics }).then(function () {
        message(status, S.cmDigestSent, 'ok');
        form.reset();
      }, function (err) { message(status, err.message, 'error'); }).then(function () { busy(button, false); });
    });
  }

  // -- /account/ ------------------------------------------------------------------------------------------------
  function field(label, input) {
    return h('div', { class: 'cm-field' }, [h('label', { for: input.id }, label), input]);
  }

  function accountPage(root) {
    var match = location.hash.match(/signin=([\w-]+)/);
    if (match) {
      history.replaceState(null, '', location.pathname + location.search);  // the token leaves the address bar
      root.textContent = '';
      root.appendChild(h('p', { class: 'cm-note' }, S.cmSigningIn));
      api('POST', '/v1/auth/verify', { token: match[1] }).then(function (data) {
        store(TOKEN, data.token);
        me = data.user;
        updateAccountButton();
        var back = null;
        try { back = JSON.parse(stored(RETURN)); } catch (e) { back = null; }
        store(RETURN, null);
        if (back && back.url && Date.now() - back.at < 3600 * 1000 && back.url.indexOf(location.origin) === 0) {
          location.href = back.url;
        } else {
          drawAccount(root);
        }
      }, function (err) { drawSignIn(root, err.message); });
      return;
    }
    if (me) drawAccount(root); else drawSignIn(root);
  }

  function drawSignIn(root, error) {
    leadVisible(true);
    root.textContent = '';
    var email = h('input', { id: 'cm-email', type: 'email', required: true, autocomplete: 'email', placeholder: 'name@utas.edu.au' });
    var button = h('button', { type: 'submit', class: 'btn-primary' }, S.cmSendLink);
    var status = h('p', { class: 'cm-message', hidden: true, role: 'status' });
    var form = h('form', { class: 'cm-card cm-signin' }, [field(S.cmEmailLabel, email), h('div', { class: 'cm-actions' }, button), status]);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      busy(button, true);
      api('POST', '/v1/auth/request', { email: email.value, lang: LANG }).then(function () {
        message(status, t('cmLinkSent', { email: email.value }), 'ok');
      }, function (err) { message(status, err.message, 'error'); }).then(function () { busy(button, false); });
    });
    root.appendChild(form);
    if (error) message(status, error, 'error');
  }

  function leadVisible(on) {
    var lead = document.querySelector('.hero-sub');
    if (lead) lead.hidden = !on;  // "We'll email you a link" is for signing in only
  }

  function drawAccount(root) {
    leadVisible(false);
    root.textContent = '';
    var grid = h('div', { class: 'cm-account' });
    root.appendChild(grid);

    // Profile
    var name = h('input', { id: 'cm-name', maxlength: '60', value: me.display_name });
    var course = h('input', { id: 'cm-course', maxlength: '100', value: me.course, placeholder: 'Master of Information Technology and Systems' });
    var languages = h('input', { id: 'cm-languages', maxlength: '100', value: me.languages, placeholder: 'English, 中文, नेपाली' });
    var lang = h('select', { id: 'cm-lang' }, [['en', 'English'], ['zh', '简体中文'], ['ne', 'नेपाली']].map(function (o) {
      return h('option', { value: o[0], selected: me.lang === o[0] }, o[1]);
    }));
    var saveButton = h('button', { type: 'submit', class: 'btn-primary' }, S.cmSave);
    var saved = h('p', { class: 'cm-message', hidden: true, role: 'status' });
    var profile = h('form', { class: 'cm-card' }, [
      h('h2', {}, S.cmProfileTitle), h('p', { class: 'cm-muted' }, me.email),
      field(S.cmDisplayName, name), field(S.cmCourse, course), field(S.cmLanguages, languages), field(S.cmEmailLanguage, lang),
      h('div', { class: 'cm-actions' }, saveButton), saved
    ]);
    profile.addEventListener('submit', function (e) {
      e.preventDefault();
      busy(saveButton, true);
      api('PATCH', '/v1/me', { display_name: name.value, course: course.value, languages: languages.value, lang: lang.value })
        .then(function (u) { me = u; updateAccountButton(); message(saved, S.cmSaved, 'ok'); },
          function (err) { message(saved, err.message, 'error'); })
        .then(function () { busy(saveButton, false); });
    });
    grid.appendChild(profile);

    // Going together
    var intros = h('section', { class: 'cm-card', id: 'buddies' }, [h('h2', {}, S.cmRequestsTitle), h('p', { class: 'cm-note' }, S.cmLoading)]);
    grid.appendChild(intros);
    api('GET', '/v1/me/intros').then(function (d) {
      intros.textContent = '';
      intros.appendChild(h('h2', {}, S.cmRequestsTitle));
      if (!d.intros.length) intros.appendChild(h('p', { class: 'cm-empty' }, S.cmRequestsEmpty));
      d.intros.forEach(function (i) {
        var text = i.direction === 'incoming' ? t('cmWantsToGo', { name: i.name, event: i.event_title }) : t('cmYouAsked', { name: i.name, event: i.event_title });
        var row = h('div', { class: 'cm-intro' }, [h('p', {}, text), i.message ? h('p', { class: 'cm-buddy-note' }, '“' + i.message + '”') : null]);
        if (i.status === 'accepted') {
          row.appendChild(h('p', {}, [h('span', { class: 'cm-tag cm-tag--ok' }, S.cmBuddyAccepted), ' ',
            h('a', { href: 'mailto:' + i.email }, t('cmEmailThem', { name: i.name }) + ' (' + i.email + ')')]));
        } else if (i.status === 'declined') {
          row.appendChild(h('span', { class: 'cm-tag' }, S.cmBuddyDeclined));
        } else if (i.direction === 'incoming') {
          var answer = function (accept) {
            return function () {
              api('POST', '/v1/intros/' + i.id, { accept: accept }).then(function () { drawAccount(root); }, function (err) { alert(err.message); });
            };
          };
          row.appendChild(h('div', { class: 'cm-actions' }, [
            h('button', { type: 'button', class: 'btn-primary', onclick: answer(true) }, S.cmAccept),
            h('button', { type: 'button', class: 'hp-btn-outline', onclick: answer(false) }, S.cmDecline)
          ]));
        } else {
          row.appendChild(h('span', { class: 'cm-tag' }, S.cmBuddyAsked));
        }
        intros.appendChild(row);
      });
    });

    // My events, and the record of events attended
    var events = h('section', { class: 'cm-card' }, [h('h2', {}, S.cmMyEventsTitle), h('p', { class: 'cm-note' }, S.cmLoading)]);
    grid.appendChild(events);
    api('GET', '/v1/me/events').then(function (d) {
      events.textContent = '';
      events.appendChild(h('h2', {}, S.cmMyEventsTitle));
      var coming = d.events.filter(function (e) { return e.status !== 'went'; });
      var went = d.events.filter(function (e) { return e.status === 'went'; });
      if (!d.events.length) events.appendChild(h('p', { class: 'cm-empty' }, h('a', { href: S.happening }, S.cmMyEventsEmpty)));
      function list(items) {
        return h('ul', { class: 'cm-event-list' }, items.map(function (e) {
          var label = e.status === 'going' ? S.cmGoing : (e.status === 'interested' ? S.cmInterested : '');
          return h('li', {}, [
            e.page ? h('a', { href: e.page }, e.title) : h('span', {}, e.title),
            h('span', { class: 'cm-muted' }, ' · ' + formatDate(e.start, e.status !== 'went') + (e.host ? ' · ' + e.host : '')),
            label ? h('span', { class: 'cm-tag' }, label) : null
          ]);
        }));
      }
      if (coming.length) { events.appendChild(h('h3', {}, S.cmComingUp)); events.appendChild(list(coming)); }
      if (went.length) {
        events.appendChild(h('h3', {}, S.cmWent));
        events.appendChild(list(went));
        var copy = h('button', { type: 'button', class: 'hp-btn-outline' }, S.cmCopyRecord);
        copy.addEventListener('click', function () {
          var month = { timeZone: 'Australia/Hobart', month: 'long', year: 'numeric' };
          var text = S.cmRecordHeading + '\n' + went.map(function (e) {
            var when = '';
            try { when = new Intl.DateTimeFormat(LOCALE, month).format(new Date(e.start)); } catch (err) { when = e.start.slice(0, 7); }
            return '- ' + e.title + (e.host ? ' (' + e.host + ')' : '') + ', ' + when;
          }).join('\n');
          navigator.clipboard.writeText(text).then(function () { copy.textContent = S.cmCopied; });
        });
        events.appendChild(h('div', { class: 'cm-actions' }, copy));
      }
    });

    // Data
    var data = h('section', { class: 'cm-card' }, [h('h2', {}, S.cmDataTitle)]);
    var actions = h('div', { class: 'cm-actions cm-actions--wrap' });
    actions.appendChild(h('button', { type: 'button', class: 'hp-btn-outline', onclick: function () {
      api('GET', '/v1/me/export').then(function (d) {
        var blob = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
        var a = h('a', { href: URL.createObjectURL(blob), download: 'tasmania-welcome-my-data.json' });
        document.body.appendChild(a); a.click(); a.remove();
      });
    } }, S.cmExport));
    actions.appendChild(h('button', { type: 'button', class: 'hp-btn-outline', onclick: function () {
      api('POST', '/v1/auth/logout').then(null, function () {}).then(function () { store(TOKEN, null); me = null; updateAccountButton(); drawSignIn(root); });
    } }, S.cmSignOut));
    actions.appendChild(h('button', { type: 'button', class: 'cm-danger', onclick: function () {
      if (!confirm(S.cmDeleteConfirm)) return;
      api('DELETE', '/v1/me').then(function () {
        store(TOKEN, null); me = null; updateAccountButton();
        root.textContent = '';
        root.appendChild(h('p', { class: 'cm-message cm-message--ok' }, S.cmDeleted));
      }, function (err) { alert(err.message); });
    } }, S.cmDelete));
    if (me.role === 'moderator' || me.role === 'admin') {
      actions.appendChild(h('a', { class: 'hp-btn-outline', href: S.account.replace(/account\/$/, 'moderate/') }, S.cmModerateLink));
    }
    data.appendChild(actions);
    grid.appendChild(data);
  }

  // -- /noticeboard/ ----------------------------------------------------------------------------------------------
  var KINDS = [
    { kind: 'wish', label: 'cmBoardWish', lead: 'cmBoardWishLead', reaction: 'cmMeToo' },
    { kind: 'achievement', label: 'cmBoardAchievement', lead: 'cmBoardAchievementLead', reaction: 'cmCongrats' },
    { kind: 'opportunity', label: 'cmBoardOpportunity', lead: 'cmBoardOpportunityLead', reaction: 'cmUseful' }
  ];
  var WORK_RIGHTS = { anyone: 'cmWrAnyone', student_visa_ok: 'cmWrStudent', full_work_rights: 'cmWrFull', citizen_or_pr: 'cmWrCitizen' };
  var OPP_TYPES = { internship: 'cmOppInternship', graduate: 'cmOppGraduate', casual: 'cmOppCasual', volunteer: 'cmOppVolunteer', other: 'cmOppOther' };

  function boardPage(root) {
    var current = (location.hash.replace('#', '') || 'wish');
    if (!KINDS.some(function (k) { return k.kind === current; })) current = 'wish';
    root.textContent = '';
    var tabs = h('div', { class: 'cm-tabs', role: 'tablist' });
    var panel = h('div', { class: 'cm-board', role: 'tabpanel' });
    var lead = document.querySelector('.hero-sub');
    KINDS.forEach(function (k) {
      tabs.appendChild(h('button', { type: 'button', role: 'tab', class: 'cm-tab', 'aria-selected': k.kind === current ? 'true' : 'false', onclick: function () {
        current = k.kind;
        history.replaceState(null, '', '#' + k.kind);
        tabs.querySelectorAll('[role="tab"]').forEach(function (b) { b.setAttribute('aria-selected', b === this ? 'true' : 'false'); }, this);
        draw();
      } }, S[k.label]));
    });
    root.appendChild(tabs);
    root.appendChild(panel);

    function draw() {
      var k = KINDS.filter(function (x) { return x.kind === current; })[0];
      if (lead) lead.textContent = S[k.lead];
      panel.textContent = '';
      panel.appendChild(me ? postForm(k, draw) : signInPrompt());
      var list = h('div', { class: 'cm-posts' }, h('p', { class: 'cm-note' }, S.cmLoading));
      panel.appendChild(list);
      if (k.kind === 'opportunity') panel.appendChild(h('p', { class: 'cm-muted cm-small' }, S.cmWorkRightsNote));
      api('GET', '/v1/posts?kind=' + k.kind + '&sort=' + (k.kind === 'wish' ? 'top' : 'new')).then(function (d) {
        list.textContent = '';
        d.pending.forEach(function (p) { list.appendChild(postCard(p, k, true)); });
        if (!d.posts.length && !d.pending.length) list.appendChild(h('p', { class: 'cm-empty' }, S.cmBoardEmpty));
        d.posts.forEach(function (p) { list.appendChild(postCard(p, k, false)); });
      }, function (err) { list.textContent = ''; list.appendChild(h('p', { class: 'cm-message cm-message--error' }, err.message)); });
    }
    draw();
  }

  function postCard(p, k, pending) {
    var meta = [];
    if (p.kind === 'opportunity') {
      if (p.meta.organisation) meta.push(p.meta.organisation);
      if (p.meta.type) meta.push(S[OPP_TYPES[p.meta.type]] || p.meta.type);
      if (p.meta.closes_on) meta.push(t('cmClosesOn', { date: formatDate(p.meta.closes_on + 'T12:00:00+10:00', false) }));
    }
    meta.push(p.author);
    var react = h('button', { type: 'button', class: 'cm-chip', 'aria-pressed': p.reacted ? 'true' : 'false', disabled: pending }, S[k.reaction] + (p.reactions ? ' · ' + p.reactions : ''));
    react.addEventListener('click', function () {
      if (!me) { goSignIn(); return; }
      api('POST', '/v1/posts/' + p.id + '/react').then(function (r) {
        react.setAttribute('aria-pressed', r.reacted ? 'true' : 'false');
        react.textContent = S[k.reaction] + (r.reactions ? ' · ' + r.reactions : '');
      });
    });
    var tools = h('div', { class: 'cm-post-tools' }, [pending ? h('span', { class: 'cm-tag' }, S.cmPending) : react]);
    if (me && !pending && !p.mine) {
      tools.appendChild(h('button', { type: 'button', class: 'cm-link', onclick: function (e) {
        var reason = prompt(S.cmReportReason);
        if (reason === null) return;
        var button = e.currentTarget;
        api('POST', '/v1/posts/' + p.id + '/report', { reason: reason }).then(function () { button.replaceWith(h('span', { class: 'cm-muted' }, S.cmReported)); });
      } }, S.cmReport));
    }
    if (me && (p.mine || me.role !== 'member')) {
      tools.appendChild(h('button', { type: 'button', class: 'cm-link', onclick: function (e) {
        var card = e.currentTarget.closest('.cm-post');
        api('DELETE', '/v1/posts/' + p.id).then(function () { card.remove(); });
      } }, S.cmDeletePost));
    }
    return h('article', { class: 'cm-post' + (pending ? ' cm-post--pending' : '') }, [
      p.kind === 'opportunity' && p.meta.work_rights ? h('span', { class: 'cm-rights cm-rights--' + p.meta.work_rights }, S[WORK_RIGHTS[p.meta.work_rights]]) : null,
      h('h3', { class: 'cm-post-title' }, p.link ? h('a', { href: p.link, target: '_blank', rel: 'noopener nofollow ugc' }, p.title + ' ↗') : p.title),
      p.body ? h('p', { class: 'cm-post-body' }, p.body) : null,
      h('p', { class: 'cm-muted cm-small' }, meta.join(' · ')),
      tools
    ]);
  }

  function postForm(k, done) {
    var id = function (name) { return 'cm-' + k.kind + '-' + name; };
    var title = h('input', { id: id('title'), required: true, minlength: '3', maxlength: '140' });
    var body = h('textarea', { id: id('body'), rows: '3', maxlength: '2000' });
    var link = h('input', { id: id('link'), type: 'url', maxlength: '500', placeholder: 'https://', required: k.kind === 'opportunity' });
    var fields = [field(S.cmPostTitle, title), field(S.cmPostBody, body), field(k.kind === 'opportunity' ? S.cmPostLinkRequired : S.cmPostLink, link)];
    var org, type, rights, closes;
    if (k.kind === 'opportunity') {
      org = h('input', { id: id('org'), maxlength: '120' });
      type = h('select', { id: id('type') }, Object.keys(OPP_TYPES).map(function (v) { return h('option', { value: v }, S[OPP_TYPES[v]]); }));
      rights = h('select', { id: id('rights') }, Object.keys(WORK_RIGHTS).map(function (v) { return h('option', { value: v }, S[WORK_RIGHTS[v]]); }));
      closes = h('input', { id: id('closes'), type: 'date' });
      fields.push(field(S.cmOrg, org), field(S.cmOppType, type), field(S.cmWorkRights, rights), field(S.cmClosesLabel, closes));
    }
    var submit = h('button', { type: 'submit', class: 'btn-primary' }, S.cmPostSubmit);
    var status = h('p', { class: 'cm-message', hidden: true, role: 'status' });
    var form = h('form', { class: 'cm-card cm-post-form' }, [
      h('p', { class: 'cm-muted cm-small' }, t('cmPostAs', { name: me.display_name }))
    ].concat(fields, [h('div', { class: 'cm-actions' }, submit), status]));
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var payload = { kind: k.kind, title: title.value, body: body.value, link: link.value };
      if (k.kind === 'opportunity') {
        payload.organisation = org.value; payload.opportunity_type = type.value; payload.work_rights = rights.value;
        if (closes.value) payload.closes_on = closes.value;
      }
      busy(submit, true);
      api('POST', '/v1/posts', payload).then(function () {
        form.reset();
        message(status, S.cmPostSent, 'ok');
        setTimeout(done, 1200);
      }, function (err) { message(status, err.message, 'error'); }).then(function () { busy(submit, false); });
    });
    return form;
  }

  // -- /suggest/ --------------------------------------------------------------------------------------------------
  function suggestPage(root) {
    root.textContent = '';
    var url = h('input', { id: 'cm-s-url', type: 'url', required: true, maxlength: '500', placeholder: 'https://events.humanitix.com/…' });
    var details = h('textarea', { id: 'cm-s-details', rows: '4', maxlength: '4000' });
    var note = h('textarea', { id: 'cm-s-note', rows: '2', maxlength: '1000' });
    // Hidden from people (CSS and the screen reader rule below); bots fill it in, and the API drops those
    var trap = h('input', { name: 'website', tabindex: '-1', autocomplete: 'off', 'aria-hidden': 'true', class: 'cm-trap' });
    var submit = h('button', { type: 'submit', class: 'btn-primary' }, S.cmSuggestSubmit);
    var status = h('p', { class: 'cm-message', hidden: true, role: 'status' });
    var form = h('form', { class: 'cm-card cm-suggest' }, [
      field(S.cmSuggestLink, url), field(S.cmSuggestDetails, details), field(S.cmSuggestNote, note), trap,
      h('div', { class: 'cm-actions cm-actions--wrap' }, [submit, h('a', { href: S.suggestIssue, target: '_blank', rel: 'noopener' }, S.cmSuggestGitHub + ' ↗')]),
      status
    ]);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      busy(submit, true);
      api('POST', '/v1/suggestions', { url: url.value, details: details.value, note: note.value, website: trap.value }).then(function (s) {
        form.reset();
        if (s.status === 'forwarded' && s.issue_url) {
          status.textContent = '';
          status.className = 'cm-message cm-message--ok';
          status.hidden = false;
          var parts = S.cmSuggestForwarded.split('{link}');
          status.appendChild(document.createTextNode(parts[0]));
          status.appendChild(h('a', { href: s.issue_url, target: '_blank', rel: 'noopener' }, s.issue_url));
          if (parts[1]) status.appendChild(document.createTextNode(parts[1]));
        } else {
          message(status, S.cmSuggestPending, 'ok');
        }
      }, function (err) { message(status, err.message, 'error'); }).then(function () { busy(submit, false); });
    });
    root.appendChild(form);
  }

  // -- /moderate/ -------------------------------------------------------------------------------------------------
  function moderatePage(root) {
    root.textContent = '';
    if (!me) { root.appendChild(signInPrompt()); return; }
    if (me.role === 'member') { root.appendChild(h('p', { class: 'cm-note' }, S.cmModOnly)); return; }
    var queue = h('div', { class: 'cm-account' });
    root.appendChild(queue);
    function section(titleKey) { var s = h('section', { class: 'cm-card' }, h('h2', {}, S[titleKey])); queue.appendChild(s); return s; }
    function draw() {
      queue.textContent = '';
      var posts = section('cmModQueue');
      var reports = section('cmModReports');
      var suggestions = section('cmModSuggestions');
      var numbers = section('cmModStats');
      api('GET', '/v1/mod/queue').then(function (q) {
        if (!q.posts.length) posts.appendChild(h('p', { class: 'cm-empty' }, S.cmModEmpty));
        q.posts.forEach(function (p) {
          var k = KINDS.filter(function (x) { return x.kind === p.kind; })[0];
          var card = postCard(p, k, true);
          card.insertBefore(h('p', { class: 'cm-muted cm-small' }, S[k.label] + ' · ' + p.author_email), card.firstChild);
          card.appendChild(h('div', { class: 'cm-actions' }, [
            h('button', { type: 'button', class: 'btn-primary', onclick: function () { decide('/v1/mod/posts/' + p.id, 'approve'); } }, S.cmApprove),
            h('button', { type: 'button', class: 'hp-btn-outline', onclick: function () { decide('/v1/mod/posts/' + p.id, 'reject'); } }, S.cmReject)
          ]));
          posts.appendChild(card);
        });
        if (!q.reports.length) reports.appendChild(h('p', { class: 'cm-empty' }, S.cmModEmpty));
        q.reports.forEach(function (r) {
          var k = KINDS.filter(function (x) { return x.kind === r.post.kind; })[0];
          var card = postCard(r.post, k, true);
          card.insertBefore(h('p', { class: 'cm-message cm-message--error' }, '“' + (r.reason || '…') + '”'), card.firstChild);
          card.appendChild(h('div', { class: 'cm-actions' }, [
            h('button', { type: 'button', class: 'btn-primary', onclick: function () { decide('/v1/mod/posts/' + r.post.id, 'hide'); } }, S.cmHide),
            h('button', { type: 'button', class: 'hp-btn-outline', onclick: function () { api('POST', '/v1/mod/reports/' + r.id + '/dismiss').then(draw); } }, S.cmDismiss)
          ]));
          reports.appendChild(card);
        });
        if (!q.suggestions.length) suggestions.appendChild(h('p', { class: 'cm-empty' }, S.cmModEmpty));
        q.suggestions.forEach(function (s) {
          suggestions.appendChild(h('div', { class: 'cm-intro' }, [
            h('p', {}, h('a', { href: s.url, target: '_blank', rel: 'noopener nofollow' }, s.url)),
            s.details ? h('p', { class: 'cm-post-body' }, s.details) : null,
            s.note ? h('p', { class: 'cm-muted' }, s.note) : null,
            h('div', { class: 'cm-actions' }, [
              h('button', { type: 'button', class: 'btn-primary', onclick: function () { decide('/v1/mod/suggestions/' + s.id, 'forward'); } }, S.cmForward),
              h('button', { type: 'button', class: 'hp-btn-outline', onclick: function () { decide('/v1/mod/suggestions/' + s.id, 'reject'); } }, S.cmReject)
            ])
          ]));
        });
      }, function (err) { posts.appendChild(h('p', { class: 'cm-message cm-message--error' }, err.message)); });
      api('GET', '/v1/mod/stats').then(function (n) {
        numbers.appendChild(h('dl', { class: 'cm-stats' }, Object.keys(n).reduce(function (acc, key) {
          return acc.concat([h('dt', {}, key.replace(/_/g, ' ')), h('dd', {}, String(n[key]))]);
        }, [])));
      });
      if (me.role === 'admin') {
        var people = section('cmModUsers');
        var search = h('input', { type: 'search', placeholder: S.cmSearchEmail, 'aria-label': S.cmSearchEmail });
        var results = h('div');
        var find = function () {
          api('GET', '/v1/mod/users?q=' + encodeURIComponent(search.value)).then(function (d) {
            results.textContent = '';
            d.users.forEach(function (u) {
              var role = h('select', { 'aria-label': S.cmRole }, ['member', 'moderator', 'admin'].map(function (r) { return h('option', { value: r, selected: u.role === r }, r); }));
              role.addEventListener('change', function () { api('POST', '/v1/mod/users/' + u.id + '/role', { role: role.value }).then(null, function (err) { alert(err.message); }); });
              results.appendChild(h('div', { class: 'cm-user' }, [h('span', {}, u.email), role]));
            });
          });
        };
        search.addEventListener('input', find);
        people.appendChild(search);
        people.appendChild(results);
        find();
      }
    }
    function decide(path, action) { api('POST', path, { action: action }).then(draw, function (err) { alert(err.message); }); }
    draw();
  }

  // -- start --------------------------------------------------------------------------------------------------------
  function start() {
    updateAccountButton();
    eventBars();
    digestForm();
    var page = document.querySelector('[data-cm-page]');
    var root = page && page.querySelector('[data-cm-root]');
    if (!root) return;
    var renderers = { account: accountPage, noticeboard: boardPage, suggest: suggestPage, moderate: moderatePage };
    var kind = page.getAttribute('data-cm-page');
    var render = renderers[kind];
    if (render) render(root);
    // A sign-in link opened in a tab that already shows the account page only changes the #fragment
    if (kind === 'account') {
      window.addEventListener('hashchange', function () {
        if (/signin=/.test(location.hash)) accountPage(root);
      });
    }
  }

  var token = stored(TOKEN);
  (token ? api('GET', '/v1/me').then(function (u) { me = u; }, function () { me = null; }) : Promise.resolve()).then(start);
})();
