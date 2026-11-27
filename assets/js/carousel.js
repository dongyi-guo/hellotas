// Site scripts: mobile menu, image carousels, the TUSA event tabs, LinkedIn reader view and post series, events filter and search, event sub-bar, copy-link buttons,
// the photo viewer, sliding toggle pills and animated in-page changes.
// Sliding is plain CSS scroll-snap, so swiping and scrolling still work if this file fails to load.
(function () {
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // An animated change inside a page (View Transitions): the browser cross-fades the page and glides each element
  // in `named` from where it was to where it ends up. The names are only set for this change and cleared after, so
  // they never clash with the page-to-page transition. Browsers without the API, and reduced motion, just update.
  // Also used by happening.js.
  function transition(update, named) {
    if (reduceMotion || !document.startViewTransition) { update(); return null; }
    named = named || [];
    named.forEach(function (el, i) { el.style.viewTransitionName = el.dataset.vt || 'vt-' + i; });
    var t = document.startViewTransition(update);
    var done = function () { named.forEach(function (el) { el.style.viewTransitionName = ''; }); };
    // A newer change skips this animation (the update itself still happens); that isn't an error
    t.ready.catch(function () {});
    t.finished.then(done, done);
    return t;
  }
  window.siteTransition = transition;

  // Toggle groups ([data-segmented]): one pill sits behind the pressed button and slides when another is pressed.
  // It follows aria-pressed, so the scripts that own the buttons don't need to know about it.
  function initSegmented(group) {
    var pill = document.createElement('span');
    pill.className = 'seg-pill';
    pill.setAttribute('aria-hidden', 'true');
    group.insertBefore(pill, group.firstChild);

    var at = null;
    function place() {
      var on = group.querySelector('[aria-pressed="true"]');
      pill.hidden = !on;
      if (!on) return;
      var to = on.offsetLeft + ',' + on.offsetTop;
      // Moving to another button: replay the stretch (seg-flow in custom.css); a resize just re-measures
      if (at !== null && to !== at && group.classList.contains('seg-animate')) {
        pill.classList.remove('seg-moving');
        void pill.offsetWidth;
        pill.classList.add('seg-moving');
      }
      at = to;
      pill.style.width = on.offsetWidth + 'px';
      pill.style.height = on.offsetHeight + 'px';
      pill.style.transform = 'translate(' + on.offsetLeft + 'px, ' + on.offsetTop + 'px)';
    }

    place();
    group.classList.add('seg-ready');
    requestAnimationFrame(function () { group.classList.add('seg-animate'); }); // no slide-in on first paint
    new MutationObserver(place).observe(group, { subtree: true, attributes: true, attributeFilter: ['aria-pressed'] });
    if (window.ResizeObserver) new ResizeObserver(place).observe(group);
  }

  // Auto-advance ring, shared by the photo carousels and the Happening page (window.siteAutoAdvance).
  // A small ring fills up over `delay` ms, then next() shows the next slide (the caller loops back to the first).
  // Clicking it pauses: it shows ⏸ until the pointer leaves, then ▶, and clicking ▶ plays again. reset() gives
  // the current slide a full turn (call it when someone moves the carousel by hand). The ring stops filling
  // while the tab is hidden or while held() says so, and starts paused for people who prefer reduced motion.
  //   ring     a button from ringButton()
  //   options  { delay, next, held }
  var RING_LENGTH = 2 * Math.PI * 10;
  function ringButton(labelPause, labelPlay, className) {
    var ring = document.createElement('button');
    ring.type = 'button';
    ring.className = 'ring-btn' + (className ? ' ' + className : '');
    ring.dataset.labelPause = labelPause;
    ring.dataset.labelPlay = labelPlay;
    ring.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true" focusable="false">' +
      '<circle class="ring-track" cx="12" cy="12" r="10"/>' +
      '<circle class="ring-fill" cx="12" cy="12" r="10" transform="rotate(-90 12 12)" stroke-dasharray="' + RING_LENGTH +
        '" stroke-dashoffset="' + RING_LENGTH + '"/>' +
      '<path class="ring-pause" d="M9.5 8.5v7M14.5 8.5v7"/>' +
      '<path class="ring-play" d="M10 8.2v7.6l6-3.8z"/>' +
      '</svg>';
    return ring;
  }
  function autoAdvance(ring, options) {
    var fill = ring.querySelector('.ring-fill');
    var playing = !reduceMotion;
    var elapsed = 0;
    var last = null;
    function setPlaying(value) {
      playing = value;
      ring.classList.toggle('is-paused', !playing);
      ring.setAttribute('aria-label', playing ? ring.dataset.labelPause : ring.dataset.labelPlay);
    }
    function tick(time) {
      var held = document.hidden || !ring.isConnected || (options.held && options.held());
      if (playing && !held && last !== null) elapsed += time - last;
      last = time;
      if (elapsed >= options.delay) { elapsed = 0; options.next(); }
      fill.setAttribute('stroke-dashoffset', RING_LENGTH * (1 - Math.min(elapsed / options.delay, 1)));
      requestAnimationFrame(tick);
    }
    ring.addEventListener('click', function () {
      setPlaying(!playing);
      ring.classList.toggle('just-paused', !playing);
    });
    ring.addEventListener('pointerleave', function () { ring.classList.remove('just-paused'); });
    ring.addEventListener('blur', function () { ring.classList.remove('just-paused'); });
    setPlaying(playing);
    requestAnimationFrame(tick);
    return { reset: function () { elapsed = 0; } };
  }
  window.siteRingButton = ringButton;
  window.siteAutoAdvance = autoAdvance;

  // Deck: one wide card per slide, used by Happening's "Recommended by us" (happening.js) and the events page's
  // "Check This Out!" ([data-deck-static]).
  // One event per slide in a scroll-snap track, so swiping works. The controls sit above the cards: ‹ › loop
  // round, the dots jump, "2 / 3" says where you are, and a ring fills up over ROTATE ms, then moves on to the
  // next event (back to the first after the last). Clicking the ring pauses it (it shows ⏸ until the pointer
  // leaves, then ▶) and clicking ▶ starts it again. The ring holds while the pointer is over a card, so a card
  // never slides away from under a click, and it starts paused for people who prefer reduced motion.
  // With fewer than two events the controls hide. Slides come and go as the days pass, so the controls are
  // rebuilt from the visible slides on every refresh().
  var ROTATE = 7000;

  function Deck(el, labels) {
    var track = el.querySelector('[data-deck-track]');
    var nav = document.createElement('div');
    nav.className = 'hp-deck-nav';
    nav.hidden = true;
    nav.innerHTML = '<button type="button" class="hp-deck-btn" data-deck-prev>‹</button>' +
      '<span class="hp-deck-dots"></span><span class="hp-deck-count" aria-hidden="true"></span>' +
      '<button type="button" class="hp-deck-btn" data-deck-next>›</button>';
    el.insertBefore(nav, track);
    var dots = nav.querySelector('.hp-deck-dots');
    var counter = nav.querySelector('.hp-deck-count');
    nav.querySelector('[data-deck-prev]').setAttribute('aria-label', labels.prev);
    nav.querySelector('[data-deck-next]').setAttribute('aria-label', labels.next);
    var index = 0;

    function slides() { return Array.prototype.filter.call(track.children, function (c) { return !c.hidden; }); }
    function mark() {
      var list = slides();
      counter.textContent = (index + 1) + ' / ' + list.length;
      Array.prototype.forEach.call(dots.children, function (dot, j) {
        if (j === index) dot.setAttribute('aria-current', 'true'); else dot.removeAttribute('aria-current');
      });
    }
    function goTo(i, instant) {
      var list = slides();
      if (!list.length) return;
      index = (i + list.length) % list.length;
      if (auto) auto.reset(); // a new slide gets a full turn of the ring
      track.scrollTo({ left: list[index].offsetLeft - list[0].offsetLeft, behavior: instant || reduceMotion ? 'auto' : 'smooth' });
      mark();
    }

    var ticking = false;
    track.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        var list = slides();
        if (!list.length) return;
        var base = list[0].offsetLeft;
        var best = 0;
        list.forEach(function (slide, j) {
          if (Math.abs(slide.offsetLeft - base - track.scrollLeft) < Math.abs(list[best].offsetLeft - base - track.scrollLeft)) best = j;
        });
        if (best !== index) { index = best; if (auto) auto.reset(); mark(); }
      });
    }, { passive: true });
    nav.querySelector('[data-deck-prev]').addEventListener('click', function () { goTo(index - 1); });
    nav.querySelector('[data-deck-next]').addEventListener('click', function () { goTo(index + 1); });
    dots.addEventListener('click', function (ev) {
      var dot = ev.target.closest('[data-dot]');
      if (dot) goTo(Number(dot.dataset.dot));
    });
    el.addEventListener('keydown', function (ev) {
      if (nav.hidden || ev.target.closest('input, textarea')) return;
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); goTo(index - 1); }
      if (ev.key === 'ArrowRight') { ev.preventDefault(); goTo(index + 1); }
    });

    // Auto-advance ring from carousel.js; it holds while the pointer is over a card
    var auto = null;
    var holding = false;
    {
      var ring = ringButton(labels.pause, labels.play, 'hp-deck-ring');
      nav.appendChild(ring);
      auto = autoAdvance(ring, {
        delay: ROTATE,
        next: function () { goTo(index + 1); },
        held: function () { return holding || nav.hidden || el.hidden; }
      });
      track.addEventListener('pointerenter', function () { holding = true; });
      track.addEventListener('pointerleave', function () { holding = false; });
    }

    this.refresh = function () {
      var n = slides().length;
      el.classList.toggle('hp-deck--multi', n > 1);
      nav.hidden = n < 2;
      if (dots.children.length !== n) {
        dots.innerHTML = '';
        for (var j = 0; j < n; j++) {
          var dot = document.createElement('button');
          dot.type = 'button';
          dot.className = 'hp-deck-dot';
          dot.dataset.dot = j;
          dot.setAttribute('aria-label', (j + 1) + ' / ' + n);
          dots.appendChild(dot);
        }
      }
      if (n) goTo(Math.min(index, n - 1), true);
    };
  }

  window.siteDeck = function (el, labels) { return new Deck(el, labels); };

  function initCarousel(root) {
    var track = root.querySelector('.carousel-track');
    var slides = track.children;
    var dots = root.querySelectorAll('.carousel-dot');
    var counter = root.querySelector('.carousel-current');
    var index = 0;
    var auto = null; // the auto-advance ring, on carousels with data-autoplay

    function goTo(i) {
      index = (i + slides.length) % slides.length;
      if (auto) auto.reset();
      track.scrollTo({ left: slides[index].offsetLeft, behavior: reduceMotion ? 'auto' : 'smooth' });
    }

    function sync() {
      var i = Math.round(track.scrollLeft / track.clientWidth);
      i = Math.max(0, Math.min(i, slides.length - 1));
      if (i !== index && auto) auto.reset(); // swiped by hand
      index = i;
      counter.textContent = index + 1;
      dots.forEach(function (dot, j) {
        if (j === index) dot.setAttribute('aria-current', 'true');
        else dot.removeAttribute('aria-current');
      });
    }

    var ticking = false;
    track.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () { sync(); ticking = false; });
    }, { passive: true });

    root.querySelector('.carousel-prev').addEventListener('click', function () { goTo(index - 1); });
    root.querySelector('.carousel-next').addEventListener('click', function () { goTo(index + 1); });
    dots.forEach(function (dot, j) {
      dot.addEventListener('click', function () { goTo(j); });
    });

    if (root.dataset.autoplay) {
      var ring = ringButton(root.dataset.labelPause, root.dataset.labelPlay, 'carousel-ring');
      root.appendChild(ring);
      auto = autoAdvance(ring, { delay: Number(root.dataset.autoplay), next: function () { goTo(index + 1); } });
    }
  }

  // LinkedIn reader view (4+ people): one face per person, showing their post (or their posts, initSeries).
  // Without this script every post stays visible, stacked.
  function initReader(reader) {
    var tabs = reader.querySelectorAll('.lp-tab');
    var panels = reader.querySelectorAll('.lp-panel');
    var counter = reader.querySelector('.lp-current');
    var index = 0;

    function show(i, focusTab) {
      index = (i + tabs.length) % tabs.length;
      tabs.forEach(function (tab, j) {
        var on = j === index;
        tab.setAttribute('aria-selected', on ? 'true' : 'false');
        tab.tabIndex = on ? 0 : -1;
        panels[j].hidden = !on;
      });
      counter.textContent = index + 1;
      if (focusTab) tabs[index].focus({ preventScroll: true });
      // Keep the selected face in the middle of the strip when it scrolls (many posts)
      var tab = tabs[index];
      if (list.scrollWidth > list.clientWidth) list.scrollTo({ left: tab.offsetLeft - (list.clientWidth - tab.offsetWidth) / 2, behavior: 'smooth' });
    }

    var list = reader.querySelector('.lp-tablist');
    function edges() {
      list.classList.toggle('is-overflowing', list.scrollWidth > list.clientWidth + 2);
      list.classList.toggle('at-end', list.scrollLeft >= list.scrollWidth - list.clientWidth - 2);
    }
    list.addEventListener('scroll', edges, { passive: true });
    window.addEventListener('resize', edges);
    edges();

    tabs.forEach(function (tab, j) {
      tab.addEventListener('click', function () { show(j); });
      tab.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight') { e.preventDefault(); show(index + 1, true); }
        if (e.key === 'ArrowLeft') { e.preventDefault(); show(index - 1, true); }
      });
    });
    reader.querySelector('.lp-prev').addEventListener('click', function () { show(index - 1); });
    reader.querySelector('.lp-next').addEventListener('click', function () { show(index + 1); });

    reader.classList.add('is-ready');
    show(0);
  }

  // Someone's posts about an event, when they posted more than once ([data-series], partials/linkedin-person.html).
  // The posts sit on top of each other (CSS grid), so the card keeps the height of the longest one and nothing
  // below jumps when it changes; the shown one fades in. Next to the author's name go ‹ ›, one dot per post,
  // "1 / 3" and the auto-advance ring, which moves on every data-autoplay ms and loops round. The ring holds
  // while the pointer is over the posts (someone reading), while the posts are hidden (another person is
  // selected in the reader) or scrolled off screen, and starts paused for people who prefer reduced motion.
  // Without this script every post stays visible, one after another.
  function initSeries(series) {
    var items = Array.prototype.slice.call(series.children).filter(function (el) { return el.classList.contains('lp-series-item'); });
    if (items.length < 2) return;
    var nav = document.createElement('div');
    nav.className = 'lp-series-nav';
    nav.innerHTML = '<button type="button" class="lp-series-btn" data-series-prev>‹</button>' +
      '<span class="lp-series-dots"></span>' +
      '<button type="button" class="lp-series-btn" data-series-next>›</button>' +
      '<span class="lp-series-count" aria-hidden="true"></span>';
    nav.querySelector('[data-series-prev]').setAttribute('aria-label', series.dataset.labelPrev);
    nav.querySelector('[data-series-next]').setAttribute('aria-label', series.dataset.labelNext);
    var dots = nav.querySelector('.lp-series-dots');
    var counter = nav.querySelector('.lp-series-count');
    items.forEach(function (_, j) {
      var dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'lp-series-dot';
      dot.setAttribute('aria-label', (j + 1) + ' / ' + items.length);
      dot.addEventListener('click', function () { show(j); });
      dots.appendChild(dot);
    });
    var index = 0;
    var auto = null;

    function show(i) {
      index = (i + items.length) % items.length;
      items.forEach(function (item, j) {
        var on = j === index;
        item.classList.toggle('is-current', on);
        item.inert = !on;
        if (on) item.removeAttribute('aria-hidden'); else item.setAttribute('aria-hidden', 'true');
      });
      Array.prototype.forEach.call(dots.children, function (dot, j) {
        if (j === index) dot.setAttribute('aria-current', 'true'); else dot.removeAttribute('aria-current');
      });
      counter.textContent = (index + 1) + ' / ' + items.length;
      var author = items[index].querySelector('.lp-author');
      if (author && nav.parentNode !== author) author.appendChild(nav);
      if (auto) auto.reset(); // a new post gets a full turn of the ring
    }

    nav.querySelector('[data-series-prev]').addEventListener('click', function () { show(index - 1); });
    nav.querySelector('[data-series-next]').addEventListener('click', function () { show(index + 1); });

    var holding = false;
    var onScreen = true;
    series.addEventListener('pointerenter', function () { holding = true; });
    series.addEventListener('pointerleave', function () { holding = false; });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) { onScreen = entries[0].isIntersecting; }).observe(series);
    }
    if (series.dataset.autoplay) {
      var ring = ringButton(series.dataset.labelPause, series.dataset.labelPlay, 'lp-series-ring');
      nav.appendChild(ring);
      auto = autoAdvance(ring, {
        delay: Number(series.dataset.autoplay),
        next: function () { show(index + 1); },
        held: function () { return holding || !onScreen || series.offsetParent === null; }
      });
    }

    // Settle on the first post without fading the others out on page load
    series.classList.add('is-ready', 'is-instant');
    show(0);
    requestAnimationFrame(function () { requestAnimationFrame(function () { series.classList.remove('is-instant'); }); });
  }

  // Photo viewer: clicking a photo inside any [data-lightbox] group shows it large.
  // Closes with the × button, a click outside the photo, or Esc; arrows and ←/→ step through the group.
  // A data-caption on the photo or a wrapper inside the group (Journey place cards) shows under it, and a
  // data-source (the LinkedIn post or official page it came from) adds an "Original post" link to the toolbar.
  // Clicking the photo zooms to 200% around that spot and clicking again goes back; while zoomed it can be
  // dragged around. The toolbar has − / level / + (the level opens a list), Download and Original post;
  // the keys +, − and 0 zoom too. 100% is the photo fitted to the screen.
  var ZOOM_LEVELS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2, 3, 4];
  var ICON_DOWNLOAD = '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false"><path d="M10 3v10m0 0-4-4m4 4 4-4M4 16h12"/></svg>';
  var ICON_OPEN = '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false"><path d="M11 4h5v5m0-5-7 7M8 5H5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-3"/></svg>';

  function initLightbox() {
    if (!document.querySelector('[data-lightbox]')) return;
    var labels = document.body.dataset;
    var dialog = document.createElement('dialog');
    dialog.className = 'lightbox';
    dialog.innerHTML =
      '<button type="button" class="lightbox-close">×</button>' +
      '<div class="lightbox-toolbar" role="toolbar">' +
        '<button type="button" class="lightbox-tool lightbox-zoom-out">−</button>' +
        '<div class="lightbox-zoom">' +
          '<button type="button" class="lightbox-tool lightbox-zoom-level" aria-haspopup="true" aria-expanded="false">100%</button>' +
          '<ul class="lightbox-zoom-menu" hidden>' + ZOOM_LEVELS.map(function (z) {
            return '<li><button type="button" data-zoom="' + z + '">' + Math.round(z * 100) + '%</button></li>';
          }).join('') + '</ul>' +
        '</div>' +
        '<button type="button" class="lightbox-tool lightbox-zoom-in">+</button>' +
        '<a class="lightbox-tool lightbox-download" download>' + ICON_DOWNLOAD + '<span></span></a>' +
        '<a class="lightbox-tool lightbox-original" target="_blank" rel="noopener">' + ICON_OPEN + '<span></span></a>' +
      '</div>' +
      '<button type="button" class="lightbox-prev">‹</button>' +
      '<figure class="lightbox-figure"><div class="lightbox-stage"><img alt=""></div>' +
        '<figcaption><span class="lightbox-caption"></span><span class="lightbox-count"></span></figcaption></figure>' +
      '<button type="button" class="lightbox-next">›</button>';
    document.body.appendChild(dialog);

    var stage = dialog.querySelector('.lightbox-stage');
    var img = stage.querySelector('img');
    var caption = dialog.querySelector('.lightbox-caption');
    var count = dialog.querySelector('.lightbox-count');
    var closeBtn = dialog.querySelector('.lightbox-close');
    var prevBtn = dialog.querySelector('.lightbox-prev');
    var nextBtn = dialog.querySelector('.lightbox-next');
    var zoomOutBtn = dialog.querySelector('.lightbox-zoom-out');
    var zoomInBtn = dialog.querySelector('.lightbox-zoom-in');
    var levelBtn = dialog.querySelector('.lightbox-zoom-level');
    var menu = dialog.querySelector('.lightbox-zoom-menu');
    var download = dialog.querySelector('.lightbox-download');
    var original = dialog.querySelector('.lightbox-original');
    closeBtn.setAttribute('aria-label', labels.lbClose);
    prevBtn.setAttribute('aria-label', labels.lbPrev);
    nextBtn.setAttribute('aria-label', labels.lbNext);
    zoomOutBtn.setAttribute('aria-label', labels.lbZoomOut);
    zoomInBtn.setAttribute('aria-label', labels.lbZoomIn);
    levelBtn.setAttribute('aria-label', labels.lbZoomLevel);
    download.querySelector('span').textContent = labels.lbDownload;
    download.setAttribute('aria-label', labels.lbDownload);

    var photos = [];
    var index = 0;
    var zoom = 1;
    var base = null; // the photo's fitted size, measured when it is first zoomed

    function setZoom(z, point) {
      z = Math.min(Math.max(z, ZOOM_LEVELS[0]), ZOOM_LEVELS[ZOOM_LEVELS.length - 1]);
      if (zoom === 1) {
        var fitted = img.getBoundingClientRect();
        base = { w: fitted.width, h: fitted.height };
      }
      var before = img.getBoundingClientRect();
      // The spot that should stay under the pointer (or the middle of the view)
      var fx = point ? (point.x - before.left) / before.width : 0.5;
      var fy = point ? (point.y - before.top) / before.height : 0.5;
      zoom = z;
      levelBtn.textContent = Math.round(z * 100) + '%';
      if (z === 1) {
        stage.classList.remove('is-zoomed');
        img.style.width = img.style.height = '';
        return;
      }
      stage.classList.add('is-zoomed');
      img.style.width = base.w * z + 'px';
      img.style.height = base.h * z + 'px';
      var view = stage.getBoundingClientRect();
      var px = point ? point.x - view.left : view.width / 2;
      var py = point ? point.y - view.top : view.height / 2;
      stage.scrollLeft = fx * base.w * z - px;
      stage.scrollTop = fy * base.h * z - py;
    }

    function step(direction) {
      var next = direction > 0
        ? ZOOM_LEVELS.filter(function (z) { return z > zoom + 0.001; })[0]
        : ZOOM_LEVELS.filter(function (z) { return z < zoom - 0.001; }).pop();
      if (next) setZoom(next);
    }

    function toggleMenu(open) {
      menu.hidden = !open;
      levelBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        menu.querySelectorAll('button').forEach(function (b) {
          b.classList.toggle('is-current', Math.abs(Number(b.dataset.zoom) - zoom) < 0.001);
        });
      }
    }

    function show(i) {
      index = (i + photos.length) % photos.length;
      var photo = photos[index];
      if (zoom !== 1) setZoom(1);
      toggleMenu(false);
      img.src = photo.src;
      img.alt = photo.alt;
      caption.textContent = photo.caption;
      count.textContent = photos.length > 1 ? (index + 1) + ' / ' + photos.length : '';
      prevBtn.hidden = nextBtn.hidden = photos.length < 2;
      download.href = photo.src;
      download.setAttribute('download', decodeURIComponent(photo.src.split('/').pop().split('?')[0]));
      original.hidden = !photo.source;
      if (photo.source) {
        var label = /linkedin\.com/.test(photo.source) ? labels.lbPost : labels.lbSource;
        original.href = photo.source;
        original.querySelector('span').textContent = label;
        original.setAttribute('aria-label', label);
      }
    }

    document.addEventListener('click', function (e) {
      var group = e.target.closest('[data-lightbox]');
      // A click on a photo, or on the button around one (its zoom badge, or Enter on the keyboard)
      var hit = e.target.closest('img:not(.carousel-backdrop), button');
      var photo = hit && (hit.tagName === 'IMG' ? hit : hit.querySelector('img:not(.carousel-backdrop)'));
      if (!group || !photo || !group.contains(photo) || dialog.contains(photo)) return;
      e.preventDefault(); // Photo Booth photos are links to the full-size file
      var nodes = Array.prototype.slice.call(group.querySelectorAll('img:not(.carousel-backdrop)'));
      photos = nodes.map(function (n) {
        var labelled = n.closest('[data-caption]');
        var sourced = n.closest('[data-source]');
        return {
          src: n.dataset.full || n.src, // the original photo; the page itself shows a resized copy
          alt: n.alt,
          caption: labelled && group.contains(labelled) ? labelled.dataset.caption : '',
          source: sourced && group.contains(sourced) ? sourced.dataset.source : ''
        };
      });
      dialog.showModal();
      show(nodes.indexOf(photo));
    });

    // Drag a zoomed photo around (touch screens scroll it natively)
    var drag = null;
    var dragged = false;
    stage.addEventListener('pointerdown', function (e) {
      if (zoom === 1 || e.pointerType === 'touch' || e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, left: stage.scrollLeft, top: stage.scrollTop };
      dragged = false;
    });
    window.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x;
      var dy = e.clientY - drag.y;
      if (!dragged && Math.abs(dx) + Math.abs(dy) > 4) {
        dragged = true;
        stage.classList.add('is-dragging');
      }
      if (dragged) {
        stage.scrollLeft = drag.left - dx;
        stage.scrollTop = drag.top - dy;
      }
    });
    window.addEventListener('pointerup', function () {
      drag = null;
      stage.classList.remove('is-dragging');
    });
    img.addEventListener('dragstart', function (e) { e.preventDefault(); });

    img.addEventListener('click', function (e) {
      if (dragged) { dragged = false; return; }
      if (zoom === 1) setZoom(2, { x: e.clientX, y: e.clientY });
      else setZoom(1);
    });

    zoomInBtn.addEventListener('click', function () { step(1); });
    zoomOutBtn.addEventListener('click', function () { step(-1); });
    levelBtn.addEventListener('click', function () { toggleMenu(menu.hidden); });
    menu.addEventListener('click', function (e) {
      var option = e.target.closest('[data-zoom]');
      if (!option) return;
      setZoom(Number(option.dataset.zoom));
      toggleMenu(false);
      levelBtn.focus();
    });

    closeBtn.addEventListener('click', function () { dialog.close(); });
    prevBtn.addEventListener('click', function () { show(index - 1); });
    nextBtn.addEventListener('click', function () { show(index + 1); });
    // Anything that isn't the photo or a control closes it: the dark backdrop and the space around the photo.
    // An open zoom list closes first.
    dialog.addEventListener('click', function (e) {
      if (!menu.hidden && !e.target.closest('.lightbox-zoom')) { toggleMenu(false); return; }
      var outside = e.target === dialog || e.target.classList.contains('lightbox-figure') ||
        (e.target === stage && zoom === 1);
      if (outside) dialog.close();
    });
    dialog.addEventListener('cancel', function (e) {
      if (!menu.hidden) { e.preventDefault(); toggleMenu(false); levelBtn.focus(); }
    });
    dialog.addEventListener('keydown', function (e) {
      if (e.target.closest('.lightbox-zoom-menu')) return;
      if (e.key === 'ArrowLeft') show(index - 1);
      if (e.key === 'ArrowRight') show(index + 1);
      if (e.key === '+' || e.key === '=') step(1);
      if (e.key === '-' || e.key === '_') step(-1);
      if (e.key === '0') setZoom(1);
    });
    window.addEventListener('resize', function () { if (dialog.open && zoom !== 1) setZoom(1); });
    dialog.addEventListener('close', function () {
      setZoom(1);
      toggleMenu(false);
      img.removeAttribute('src');
    });
  }

  // Event detail page: a slim bar with the back link and title slides in under the sticky header
  // once the page title has scrolled out of view, and slides away again when it comes back.
  function initSubbar(bar) {
    var anchor = document.querySelector('[data-subbar-anchor]');
    var header = document.querySelector('.site-header');
    if (!anchor || !header) return;
    var focusables = bar.querySelectorAll('a, button');
    var visible = false;

    function setVisible(value) {
      if (value === visible) return;
      visible = value;
      bar.classList.toggle('is-visible', visible);
      bar.setAttribute('aria-hidden', visible ? 'false' : 'true');
      focusables.forEach(function (el) { el.tabIndex = visible ? 0 : -1; });
    }

    // Show once the title's bottom edge has gone up behind the sticky header.
    function update() {
      var headerHeight = header.offsetHeight;
      bar.style.top = headerHeight + 'px';
      setVisible(anchor.getBoundingClientRect().bottom < headerHeight);
    }

    bar.querySelector('.event-subbar-title').addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
    });
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  }

  // "Copy link" buttons: copy data-copy to the clipboard and show data-copied for a moment.
  function initCopy(button) {
    var label = button.textContent;
    var timer;
    button.addEventListener('click', function () {
      var text = button.dataset.copy;
      var done = function () {
        button.textContent = button.dataset.copied;
        button.classList.add('is-copied');
        clearTimeout(timer);
        timer = setTimeout(function () {
          button.textContent = label;
          button.classList.remove('is-copied');
        }, 2000);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done, function () { window.prompt('', text); });
      } else {
        window.prompt('', text); // older browsers / plain http: let the visitor copy it by hand
      }
    });
  }

  // Events list: year buttons (All / 2026 / 2025 …), a text search over each card's data-search, and the event count.
  // Every word typed must appear somewhere in the event. The choice is kept in the address (?year=…&q=…)
  // so a filtered view can be bookmarked or shared. Without this script every event stays visible.
  function initEventFilter(root) {
    var tabs = root.querySelectorAll('.year-tab');
    var input = root.querySelector('.events-search-input');
    var status = root.querySelector('.events-status');
    var count = root.querySelector('.events-count');
    var clearLink = status.querySelector('.events-clear');
    var announce = root.querySelector('.events-announce');
    var empty = root.querySelector('.events-empty');
    var groups = root.querySelectorAll('.events-year');
    var year = 'all';

    // Case, accents and full-width letters don't matter: "Pax", "PAX" and "ＰＡＸ" all match.
    function fold(text) {
      return text.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
    }

    var cards = Array.prototype.map.call(root.querySelectorAll('.event-card'), function (card) {
      return { el: card, text: fold(card.dataset.search || '') };
    });

    function apply() {
      var terms = fold(input.value).split(/\s+/).filter(Boolean);
      var shown = 0;

      groups.forEach(function (group) {
        var inYear = year === 'all' || group.dataset.year === year;
        var visible = 0;
        cards.forEach(function (card) {
          if (!group.contains(card.el)) return;
          var match = inYear && terms.every(function (t) { return card.text.indexOf(t) !== -1; });
          card.el.hidden = !match;
          if (match) visible++;
        });
        group.hidden = visible === 0;
        shown += visible;
      });

      tabs.forEach(function (tab) {
        var on = tab.dataset.year === year;
        tab.classList.toggle('active', on);
        tab.setAttribute('aria-pressed', on ? 'true' : 'false');
      });

      var filtering = year !== 'all' || terms.length > 0;
      var message = (shown === 1 ? count.dataset.single : count.dataset.plural).replace('{n}', shown);
      status.hidden = shown === 0; // the empty-state box says it instead
      clearLink.hidden = !filtering;
      empty.hidden = shown > 0;
      count.textContent = message;
      announce.textContent = message;

      var params = new URLSearchParams(location.search);
      if (year === 'all') params.delete('year'); else params.set('year', year);
      if (input.value.trim()) params.set('q', input.value.trim()); else params.delete('q');
      var query = params.toString();
      history.replaceState(null, '', location.pathname + (query ? '?' + query : '') + location.hash);
    }

    // Year and clear-filter changes animate: cards fade out or in and the rest glide to their new places.
    // Typing stays instant; cards that come back fade in (.events-typing in custom.css).
    var controls = root.querySelector('.events-controls');
    controls.dataset.vt = 'ev-controls';
    function animated(update) {
      var moving = [controls].concat(
        Array.prototype.slice.call(root.querySelectorAll('.year-heading, .year-divider, .event-card, .events-empty')),
        Array.prototype.slice.call(document.querySelectorAll('.bottom-note, .site-footer'))
      );
      transition(update, moving);
    }

    function clear() {
      animated(function () {
        year = 'all';
        input.value = '';
        apply();
      });
      input.focus();
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        if (tab.dataset.year === year) return;
        animated(function () { year = tab.dataset.year; apply(); });
      });
    });
    input.addEventListener('input', function () {
      root.classList.add('events-typing');
      apply();
    });
    root.querySelectorAll('.events-clear').forEach(function (button) {
      button.addEventListener('click', clear);
    });

    // Restore a filtered view from the address, e.g. events/?year=2025&q=melbourne
    var params = new URLSearchParams(location.search);
    if (params.get('year') && root.querySelector('.year-tab[data-year="' + params.get('year') + '"]')) year = params.get('year');
    if (params.get('q')) input.value = params.get('q');
    apply();
  }

  // Narrow screens: the ☰ button opens the menu panel under the header.
  // Closes on a link click, a click outside, Esc, or when the window widens back to desktop.
  function initMobileMenu(button) {
    var menu = document.getElementById(button.getAttribute('aria-controls'));
    if (!menu) return;

    function setOpen(open) {
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      button.setAttribute('aria-label', open ? button.dataset.labelClose : button.dataset.labelOpen);
      menu.hidden = !open;
    }

    button.addEventListener('click', function () { setOpen(menu.hidden); });
    menu.addEventListener('click', function (e) { if (e.target.closest('a')) setOpen(false); });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !menu.contains(e.target) && !button.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) { setOpen(false); button.focus(); }
    });
    window.addEventListener('resize', function () {
      if (getComputedStyle(button).display === 'none') setOpen(false);
    });
  }

  // Header channels (header.html): the button opens the list of platforms; it closes on a choice, a click outside,
  // or Esc. A platform whose account isn't set up yet opens a small "coming soon" note with its icon, which closes
  // with its button, Esc, or a click outside the card; focus goes back to the channels button.
  function initChannels() {
    var more = document.querySelector('.channel-more');
    var menu = more && document.getElementById(more.getAttribute('aria-controls'));
    function setMenu(open) {
      if (!menu) return;
      more.setAttribute('aria-expanded', open ? 'true' : 'false');
      menu.hidden = !open;
    }
    if (menu) {
      more.addEventListener('click', function () { setMenu(menu.hidden); });
      document.addEventListener('click', function (e) {
        if (!menu.hidden && (!more.parentNode.contains(e.target) || e.target.closest('.channel-menu-item'))) setMenu(false);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !menu.hidden) { setMenu(false); more.focus(); }
      });
    }

    var dialog = document.querySelector('.channel-dialog');
    if (!dialog || !dialog.showModal) return;
    var opener = null;
    document.addEventListener('click', function (e) {
      var button = e.target.closest('[data-channel-soon]');
      if (!button) return;
      opener = more || button;
      dialog.querySelector('[data-channel-icon]').innerHTML = button.querySelector('svg').outerHTML;
      dialog.querySelector('[data-channel-title]').textContent = button.dataset.channelSoon;
      dialog.querySelector('[data-channel-text]').textContent = button.dataset.channelSoonText;
      dialog.showModal();
      dialog.querySelector('[data-channel-close]').focus();
    });
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog || e.target.closest('[data-channel-close]')) dialog.close();
    });
    dialog.addEventListener('close', function () {
      if (opener && opener.offsetWidth) opener.focus();
    });
  }

  // Embedded maps (layouts/partials/place-card.html) get their address only when they are about to be seen
  function initMaps() {
    var maps = document.querySelectorAll('iframe[data-map-src]');
    if (!maps.length) return;
    function load(frame) { frame.src = frame.dataset.mapSrc; frame.removeAttribute('data-map-src'); }
    if (!('IntersectionObserver' in window)) { maps.forEach(load); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        load(entry.target);
      });
    }, { rootMargin: '300px 0px' });
    maps.forEach(function (frame) { io.observe(frame); });
  }

  // Two-week events calendar in a place card (the TUSA card on the UTAS page): the server writes the events as a
  // plain list; this turns it into Monday-to-Sunday weeks, starting with the week of today in Hobart. ‹ › move a
  // week at a time, from this week to the last week with an event. Past days fade; on phones only days with events
  // show (custom.css). Event times are Hobart times written as "YYYY-MM-DDTHH:MM", so all the date maths is done in
  // UTC on those numbers and no visitor's own time zone gets in the way.
  function initEventCalendar(root) {
    var list = root.querySelector('[data-cal-body]');
    var locale = root.dataset.locale;
    var DAY = 864e5;
    var events = Array.prototype.map.call(list.querySelectorAll('[data-start]'), function (li) {
      var a = li.querySelector('a');
      return { start: li.dataset.start, day: li.dataset.start.slice(0, 10), title: a.textContent, href: a.href };
    });
    function utc(key) { return Date.parse(key + 'T00:00:00Z'); }
    function key(ms) { return new Date(ms).toISOString().slice(0, 10); }
    function fmt(ms, opts) { return new Intl.DateTimeFormat(locale, Object.assign({ timeZone: 'UTC' }, opts)).format(new Date(ms)); }
    var today = new Date().toLocaleDateString('en-CA', { timeZone: 'Australia/Hobart' });
    var first = utc(today) - ((new Date(utc(today)).getUTCDay() + 6) % 7) * DAY; // this week's Monday
    var last = events.reduce(function (m, e) { return Math.max(m, utc(e.day)); }, first);
    var maxWeek = Math.floor((last - first) / (7 * DAY));
    var week = 0;

    var grid = document.createElement('div');
    grid.className = 'event-cal-grid';
    list.replaceWith(grid);
    var nav = root.querySelector('.event-cal-nav');
    var prev = root.querySelector('[data-cal-prev]');
    var next = root.querySelector('[data-cal-next]');
    var range = root.querySelector('[data-cal-range]');
    nav.hidden = false;

    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text) n.textContent = text;
      return n;
    }

    function render() {
      var from = first + week * 7 * DAY;
      grid.textContent = '';
      for (var d = 0; d < 7; d++) grid.appendChild(el('div', 'event-cal-dow', fmt(from + d * DAY, { weekday: 'short' })));
      var any = false;
      for (var i = 0; i < 14; i++) {
        var ms = from + i * DAY;
        var k = key(ms);
        var todays = events.filter(function (e) { return e.day === k; });
        var cell = el('div', 'event-cal-day' + (k < today ? ' is-past' : '') + (k === today ? ' is-today' : '') + (todays.length ? '' : ' is-empty'));
        var label = el('div', 'event-cal-date');
        label.appendChild(el('span', 'event-cal-wday', fmt(ms, { weekday: 'long' }) + ' '));
        label.appendChild(document.createTextNode(fmt(ms, (i === 0 || k.slice(8) === '01') ? { day: 'numeric', month: 'short' } : { day: 'numeric' })));
        cell.appendChild(label);
        todays.forEach(function (e) {
          var a = el('a', 'event-cal-event');
          a.href = e.href;
          a.target = '_blank';
          a.rel = 'noopener';
          if (e.start.length > 10) {
            var t = el('time', '', fmt(Date.parse(e.start + ':00Z'), { hour: 'numeric', minute: '2-digit' }));
            t.dateTime = e.start;
            a.appendChild(t);
          }
          a.title = e.title;
          a.appendChild(el('span', 'event-cal-title', e.title));
          cell.appendChild(a);
          if (k >= today) any = true;
        });
        grid.appendChild(cell);
      }
      if (!any) grid.appendChild(el('p', 'event-cal-empty', root.dataset.empty));
      var end = from + 13 * DAY;
      range.textContent = Intl.DateTimeFormat.prototype.formatRange
        ? new Intl.DateTimeFormat(locale, { timeZone: 'UTC', day: 'numeric', month: 'short' }).formatRange(new Date(from), new Date(end))
        : fmt(from, { day: 'numeric', month: 'short' }) + ' – ' + fmt(end, { day: 'numeric', month: 'short' });
      prev.disabled = week === 0;
      next.disabled = week >= maxWeek;
    }

    prev.addEventListener('click', function () { if (week > 0) { week--; render(); } });
    next.addEventListener('click', function () { if (week < maxWeek) { week++; render(); } });
    render();
  }

  // A swipeable row of cards ([data-rail], e.g. the award winners on an event page): the ‹ › buttons appear
  // only when the row is wider than the screen, and each one fades out at its end of the row
  function initRail(root) {
    var track = root.querySelector('.award-rail, .rail-track');
    var nav = root.querySelector('.rail-nav');
    if (!track || !nav) return;
    var prev = nav.querySelector('.rail-prev');
    var next = nav.querySelector('.rail-next');

    function update() {
      var max = track.scrollWidth - track.clientWidth;
      nav.hidden = max <= 2;
      prev.disabled = track.scrollLeft <= 2;
      next.disabled = track.scrollLeft >= max - 2;
      root.classList.toggle('rail-more-start', !nav.hidden && !prev.disabled);
      root.classList.toggle('rail-more-end', !nav.hidden && !next.disabled);
    }

    function step(dir) {
      var card = track.firstElementChild;
      var gap = parseFloat(getComputedStyle(track).columnGap) || 0;
      var width = card ? card.getBoundingClientRect().width + gap : track.clientWidth;
      // A whole number of cards, so the row always stops on a card's edge
      var cards = Math.max(1, Math.floor((track.clientWidth + gap) / width));
      track.scrollBy({ left: dir * cards * width, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }

    prev.addEventListener('click', function () { step(-1); });
    next.addEventListener('click', function () { step(1); });
    track.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  }

  // TUSA tile on the UTAS page (partials/tusa-showcase.html): the event tabs show one event at a time; ←/→, Home
  // and End move between them. Without this script the tabs stay hidden and every event shows, one after another.
  function initShowcase(root) {
    var list = root.querySelector('[role="tablist"]');
    if (!list) return;
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var panels = tabs.map(function (tab) { return document.getElementById(tab.getAttribute('aria-controls')); });
    var index = 0;

    function select(i) {
      tabs.forEach(function (tab, j) {
        var on = j === i;
        tab.setAttribute('aria-selected', on ? 'true' : 'false');
        tab.tabIndex = on ? 0 : -1;
        panels[j].hidden = !on;
      });
      window.dispatchEvent(new Event('resize')); // the strip that just appeared measures itself (initRail)
    }

    function show(i, focus) {
      i = (i + tabs.length) % tabs.length;
      if (i === index) return;
      index = i;
      if (focus) tabs[i].focus();
      transition(function () { select(i); });
    }

    tabs.forEach(function (tab, j) {
      tab.addEventListener('click', function () { show(j); });
      tab.addEventListener('keydown', function (e) {
        var to = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (to === undefined) return;
        e.preventDefault();
        show(to, true);
      });
    });

    list.hidden = false;
    root.classList.add('is-ready');
    select(0);
  }

  document.querySelectorAll('.nav-toggle').forEach(initMobileMenu);
  document.querySelectorAll('[data-showcase]').forEach(initShowcase);
  document.querySelectorAll('[data-rail]').forEach(initRail);
  document.querySelectorAll('[data-deck-static]').forEach(function (el) {
    new Deck(el, { prev: el.dataset.labelPrev, next: el.dataset.labelNext, pause: el.dataset.labelPause, play: el.dataset.labelPlay }).refresh();
  });
  document.querySelectorAll('[data-event-cal]').forEach(initEventCalendar);
  initMaps();
  initChannels();
  document.querySelectorAll('[data-carousel]').forEach(initCarousel);
  document.querySelectorAll('[data-copy]').forEach(initCopy);
  document.querySelectorAll('[data-event-filter]').forEach(initEventFilter);
  document.querySelectorAll('[data-subbar]').forEach(initSubbar);
  document.querySelectorAll('[data-series]').forEach(initSeries);
  document.querySelectorAll('[data-reader]').forEach(initReader);
  initLightbox();
  // After the deferred page scripts (happening.js builds its calendar toggle) have run
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-segmented]').forEach(initSegmented);
  });
})();
