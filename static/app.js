/* Theme toggle */
(function () {
  var toggle = document.getElementById('theme-toggle');
  if (!toggle) return;

  toggle.addEventListener('click', function () {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('hatchery-theme', next);
  });
})();

/* Sidebar collapse toggle */
(function () {
  var sidebar = document.getElementById('sidebar');
  var btn = document.getElementById('sidebar-toggle');
  if (!sidebar || !btn) return;

  /* Apply saved state (suppress transition on init, then re-enable) */
  if (localStorage.getItem('hatchery-sidebar-collapsed') === 'true') {
    sidebar.classList.add('collapsed');
  }
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      document.documentElement.classList.remove('sidebar-collapsed-init');
    });
  });

  btn.addEventListener('click', function () {
    var collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('hatchery-sidebar-collapsed', collapsed);
    btn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    btn.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
  });
})();
