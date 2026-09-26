// ponytail: vars-only theme; button injected into navbar, no per-page navbar edits; light default
(function() {
  var KEY = 'js_theme';
  function get() {
    try { return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; }
    catch (e) { return 'light'; }
  }
  function paint(t) {
    document.documentElement.dataset.theme = t;
    var b = document.getElementById('theme-toggle');
    if (b) b.innerHTML = (t === 'light' ? '&#9790;' : '&#9788;') + ' Switch mode';
  }
  paint(get());
  document.addEventListener('DOMContentLoaded', function() {
    var nav = document.querySelector('.navbar nav');
    if (!nav || document.getElementById('theme-toggle')) return;
    var b = document.createElement('button');
    b.id = 'theme-toggle';
    b.className = 'btn';
    b.type = 'button';
    b.setAttribute('aria-label', 'Switch mode');
    b.style.marginRight = '4px';
    b.onclick = function() {
      var t = get() === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(KEY, t); } catch (e) {}
      paint(t);
      if (typeof render === 'function') { try { render(); } catch (e) {} }
    };
    nav.insertBefore(b, nav.firstChild);
    paint(get());
  });
})();
