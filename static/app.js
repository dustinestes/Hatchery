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

/* Dual listbox — automations */
(function () {
  var available = document.getElementById('available-scripts');
  var selected = document.getElementById('selected-scripts');
  var addBtn = document.getElementById('add-script');
  var removeBtn = document.getElementById('remove-script');
  var upBtn = document.getElementById('move-up');
  var downBtn = document.getElementById('move-down');
  var hidden = document.getElementById('automations-hidden');
  var form = document.getElementById('hatch-form');

  if (!available || !selected) return;

  function selectItem(list, item) {
    list.querySelectorAll('.listbox-item').forEach(function (el) {
      el.classList.remove('selected');
    });
    item.classList.add('selected');
  }

  available.addEventListener('click', function (e) {
    var item = e.target.closest('.listbox-item');
    if (item) selectItem(available, item);
  });

  selected.addEventListener('click', function (e) {
    var item = e.target.closest('.listbox-item');
    if (item) selectItem(selected, item);
  });

  available.addEventListener('dblclick', function (e) {
    var item = e.target.closest('.listbox-item');
    if (item) { selected.appendChild(item); item.classList.remove('selected'); }
  });

  selected.addEventListener('dblclick', function (e) {
    var item = e.target.closest('.listbox-item');
    if (item) { available.appendChild(item); item.classList.remove('selected'); }
  });

  if (addBtn) addBtn.addEventListener('click', function () {
    var item = available.querySelector('.listbox-item.selected');
    if (item) { selected.appendChild(item); item.classList.remove('selected'); }
  });

  if (removeBtn) removeBtn.addEventListener('click', function () {
    var item = selected.querySelector('.listbox-item.selected');
    if (item) { available.appendChild(item); item.classList.remove('selected'); }
  });

  if (upBtn) upBtn.addEventListener('click', function () {
    var item = selected.querySelector('.listbox-item.selected');
    if (item && item.previousElementSibling) {
      selected.insertBefore(item, item.previousElementSibling);
    }
  });

  if (downBtn) downBtn.addEventListener('click', function () {
    var item = selected.querySelector('.listbox-item.selected');
    if (item && item.nextElementSibling) {
      selected.insertBefore(item.nextElementSibling, item);
    }
  });

  /* Sync hidden select before submit so automations values are posted */
  if (form) form.addEventListener('submit', function () {
    hidden.innerHTML = '';
    selected.querySelectorAll('.listbox-item').forEach(function (item) {
      var opt = document.createElement('option');
      opt.value = item.dataset.value;
      opt.selected = true;
      hidden.appendChild(opt);
    });
  });
})();

/* Export mode toggle — show/hide new vs append panel */
(function () {
  var modeNew = document.getElementById('export-mode-new');
  var modeAppend = document.getElementById('export-mode-append');
  var panelNew = document.getElementById('export-new');
  var panelAppend = document.getElementById('export-append');

  if (!modeNew || !modeAppend) return;

  function updatePanels() {
    if (modeNew.checked) {
      panelNew.removeAttribute('hidden');
      panelAppend.setAttribute('hidden', '');
    } else {
      panelAppend.removeAttribute('hidden');
      panelNew.setAttribute('hidden', '');
    }
  }

  modeNew.addEventListener('change', updatePanels);
  modeAppend.addEventListener('change', updatePanels);
})();

/* Notification system — toast, bell badge, tray, notifications table */
(function () {
  var LAST_READ_KEY = 'hatchery-notif-last-read';

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function timeAgo(iso) {
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function showToast(message, tier) {
    var container = document.getElementById('toast-container');
    if (!container) return;
    var el = document.createElement('div');
    el.className = 'toast toast--' + tier;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity 300ms';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 320);
    }, 4000);
  }

  function updateBadge(items, unresolvedWarningCount) {
    var badge = document.getElementById('notif-badge');
    if (!badge) return;
    var lastRead = localStorage.getItem(LAST_READ_KEY) || '1970-01-01T00:00:00.000Z';
    var unread = items.filter(function (n) { return n.created_at > lastRead; }).length;
    if (unread > 0 || unresolvedWarningCount > 0) {
      badge.textContent = unread > 9 ? '9+' : (unread || '');
      badge.style.display = 'flex';
      badge.className = 'notif-badge' + (unresolvedWarningCount > 0 ? ' notif-badge--warning' : '');
    } else {
      badge.style.display = 'none';
    }
  }

  function populateTray(items) {
    var list = document.getElementById('notif-tray-list');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="notif-tray-empty">No recent notifications</div>';
      return;
    }
    list.innerHTML = items.slice(0, 5).map(function (n) {
      return '<div class="notif-tray-item">' +
        '<div class="notif-tray-meta">' +
        '<span class="notif-tier-badge notif-tier-badge--' + escapeHtml(n.tier) + '">' + escapeHtml(n.tier) + '</span>' +
        '<span class="notif-tray-time">' + timeAgo(n.created_at) + '</span>' +
        '</div>' +
        '<div class="notif-tray-msg">' + escapeHtml(n.message) + '</div>' +
        '</div>';
    }).join('');
  }

  function pollNotifications() {
    fetch('/api/notifications')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var items = data.items || [];
        var warnCount = data.unresolved_warning_count || 0;
        var lastRead = localStorage.getItem(LAST_READ_KEY) || '1970-01-01T00:00:00.000Z';
        items.forEach(function (n) {
          if (n.created_at > lastRead) showToast(n.message, n.tier);
        });
        updateBadge(items, warnCount);
        populateTray(items);
        localStorage.setItem(LAST_READ_KEY, new Date().toISOString());
      })
      .catch(function () {});
  }

  /* Bell tray toggle */
  var bellBtn = document.getElementById('notif-bell');
  var tray = document.getElementById('notif-tray');
  if (bellBtn && tray) {
    bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      tray.classList.toggle('open');
    });
    document.addEventListener('click', function (e) {
      if (tray.classList.contains('open') && !tray.contains(e.target) && e.target !== bellBtn) {
        tray.classList.remove('open');
      }
    });
  }

  /* Notifications table — filter */
  var filterBtns = document.querySelectorAll('.notif-filter-btn');
  filterBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterBtns.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var filter = btn.dataset.filter;
      document.querySelectorAll('#notif-tbody tr').forEach(function (row) {
        row.style.display = (filter === 'all' || row.dataset.tier === filter) ? '' : 'none';
      });
    });
  });

  /* Notifications table — dismiss */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.btn-dismiss');
    if (!btn) return;
    var id = btn.dataset.id;
    fetch('/api/notifications/' + id + '/dismiss', { method: 'POST' })
      .then(function () {
        var row = btn.closest('tr');
        if (row) {
          var cell = row.querySelector('.notif-table-status');
          if (cell) {
            cell.innerHTML = '<span class="notif-status-badge notif-status-badge--dismissed">Dismissed</span>';
          }
        }
      })
      .catch(function () {});
  });

  pollNotifications();
})();

/* Clutch filename conditional required — only required when an export action is submitted in "new" mode */
(function () {
  var filenameInput = document.getElementById('clutch_filename');
  var modeNew = document.getElementById('export-mode-new');
  var exportBtns = document.querySelectorAll('[value="export_clutch"], [value="export_and_hatch"]');
  var hatchBtn = document.querySelector('[value="hatch"]');

  if (!filenameInput || !modeNew) return;

  exportBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filenameInput.required = modeNew.checked;
    });
  });

  if (hatchBtn) hatchBtn.addEventListener('click', function () {
    filenameInput.required = false;
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
