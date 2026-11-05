// Kickstart's arrival checklist (layouts/journey/step1.html): remembers ticks in this browser. With the community
// API switched on and the visitor signed in, ticks are also kept in their account so they follow them between
// devices: the first time, this device's ticks are merged into the account; after that the account decides.
(function () {
  'use strict';
  var root = document.querySelector('[data-checklist]');
  if (!root) return;
  var boxes = Array.prototype.slice.call(root.querySelectorAll('[data-checklist-item]'));
  var progress = root.querySelector('[data-checklist-progress]');
  var KEY = 'hellotas.checklist';
  var MERGED = 'hellotas.checklist.merged';
  var meta = document.querySelector('meta[name="hellotas-api"]');
  var api = meta && meta.content ? meta.content.replace(/\/+$/, '') : '';
  var token = null;
  var synced = false;

  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode: in memory only */ } }
  var state = {};
  try { state = JSON.parse(read(KEY)) || {}; } catch (e) { state = {}; }
  token = read('hellotas.session');

  function render() {
    var done = 0;
    boxes.forEach(function (box) {
      box.checked = !!state[box.getAttribute('data-checklist-item')];
      if (box.checked) done++;
    });
    if (!progress) return;
    progress.hidden = false;
    progress.textContent = progress.getAttribute('data-template').replace('{done}', done).replace('{total}', boxes.length)
      + ' · ' + progress.getAttribute(synced ? 'data-synced' : 'data-local');
  }

  function remember(doneIds) {
    state = {};
    doneIds.forEach(function (id) { state[id] = true; });
    write(KEY, JSON.stringify(state));
    synced = true;
    render();
  }

  function call(method, body) {
    var options = { method: method, headers: { 'Authorization': 'Bearer ' + token } };
    if (body) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return fetch(api + '/v1/me/checklist', options).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function fail() { synced = false; render(); }

  root.addEventListener('change', function (e) {
    var box = e.target.closest('[data-checklist-item]');
    if (!box) return;
    var id = box.getAttribute('data-checklist-item');
    if (box.checked) state[id] = true; else delete state[id];
    write(KEY, JSON.stringify(state));
    render();
    if (api && token) {
      call('POST', box.checked ? { done: [id], undone: [] } : { done: [], undone: [id] })
        .then(function (data) { remember(data.done); }, fail);
    }
  });

  render();
  if (api && token) {
    var mark = token.slice(-12);
    if (read(MERGED) !== mark) {
      call('POST', { done: Object.keys(state), undone: [] })
        .then(function (data) { write(MERGED, mark); remember(data.done); }, fail);
    } else {
      call('GET').then(function (data) { remember(data.done); }, fail);
    }
  }
})();
