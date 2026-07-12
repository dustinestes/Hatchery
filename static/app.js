/* VM row builder — shared between /build and /edit */
window.hatchery = window.hatchery || {};
hatchery.vmRows = (function () {
  function init(containerId, templateId) {
    var container = document.getElementById(containerId);
    var template = document.getElementById(templateId);
    if (!container || !template) return null;

    var rowIdx = 0;
    var isDirty = false;

    // ── Script row helpers (shared across initScriptList and addRow) ──────────

    function renderParamFields(scriptItem, params, savedParams) {
      var existing = scriptItem.querySelector('.script-params');
      if (existing) existing.remove();
      if (!params || !params.length) return;
      var div = document.createElement('div');
      div.className = 'script-params';
      params.forEach(function (p) {
        var fieldRow = document.createElement('div');
        fieldRow.className = 'script-param-row';
        var label = document.createElement('label');
        label.className = 'script-param-label';
        label.textContent = p.name + (p.mandatory ? ' *' : '');
        if (p.help) label.title = p.help;
        var input = document.createElement('input');
        input.className = 'script-param-input';
        input.type = 'text';
        input.dataset.param = p.name;
        input.placeholder = p.default != null ? String(p.default) : '';
        input.value = (savedParams && savedParams[p.name] != null) ? savedParams[p.name] : '';
        if (p.mandatory && p.default == null) input.required = true;
        fieldRow.appendChild(label);
        fieldRow.appendChild(input);
        div.appendChild(fieldRow);
      });
      scriptItem.querySelector('.script-item-params').appendChild(div);
    }

    function addScriptItem(list, scriptName, rebootAfter, savedParams) {
      var item = document.createElement('div');
      item.className = 'script-item';
      item.dataset.scriptName = scriptName;
      var CHEVRON_UP = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="18 15 12 9 6 15"/></svg>';
      var CHEVRON_DOWN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
      var CLOSE = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
      item.innerHTML =
        '<div class="script-item-header">' +
          '<span class="script-item-name">' + scriptName + '</span>' +
          '<label class="script-item-reboot-label">' +
            '<input type="checkbox" class="vm-script-reboot"' + (rebootAfter ? ' checked' : '') + '> Reboot after' +
          '</label>' +
          '<div class="script-item-actions">' +
            '<button type="button" class="btn-listbox vm-script-up" title="Move up" aria-label="Move up">' + CHEVRON_UP + '</button>' +
            '<button type="button" class="btn-listbox vm-script-down" title="Move down" aria-label="Move down">' + CHEVRON_DOWN + '</button>' +
            '<button type="button" class="btn-icon vm-script-remove" title="Remove" aria-label="Remove script">' + CLOSE + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="script-item-params"></div>';

      item.querySelector('.vm-script-up').addEventListener('click', function () {
        if (item.previousElementSibling) list.insertBefore(item, item.previousElementSibling);
        isDirty = true;
      });
      item.querySelector('.vm-script-down').addEventListener('click', function () {
        if (item.nextElementSibling) list.insertBefore(item.nextElementSibling, item);
        isDirty = true;
      });
      item.querySelector('.vm-script-remove').addEventListener('click', function () {
        item.remove();
        isDirty = true;
      });

      list.appendChild(item);

      // Fetch params and render fields; savedParams pre-fills values
      fetch('/api/automation/scripts/' + encodeURIComponent(scriptName) + '/params')
        .then(function (r) { return r.json(); })
        .then(function (params) { renderParamFields(item, params, savedParams); })
        .catch(function () {});
    }

    function initScriptList(row) {
      var list = row.querySelector('.vm-scripts-list');
      var select = row.querySelector('.vm-script-select');
      var addBtn = row.querySelector('.vm-add-script');
      var refreshBtn = row.querySelector('.vm-refresh-scripts');

      if (!list || !select) return;

      if (addBtn) {
        addBtn.addEventListener('click', function () {
          var name = select.value;
          if (!name) return;
          var already = Array.from(list.querySelectorAll('.script-item'))
            .some(function (el) { return el.dataset.scriptName === name; });
          if (already) return;
          addScriptItem(list, name, false, null);
          select.value = '';
          isDirty = true;
        });
      }

      if (refreshBtn) {
        refreshBtn.addEventListener('click', function () {
          refreshBtn.disabled = true;
          fetch('/api/automation/scripts')
            .then(function (r) { return r.json(); })
            .then(function (files) {
              var current = select.value;
              select.innerHTML = '<option value="">— select a script to add —</option>';
              files.forEach(function (f) {
                var opt = document.createElement('option');
                opt.value = f;
                opt.textContent = f;
                if (f === current) opt.selected = true;
                select.appendChild(opt);
              });
            })
            .catch(function () {})
            .finally(function () { refreshBtn.disabled = false; });
        });
      }
    }

    function addRow(vmData) {
      var clone = template.content.cloneNode(true);
      var row = clone.querySelector('.vm-row');
      row.dataset.vmIndex = rowIdx++;

      var toggleBtn = row.querySelector('.vm-row-toggle');
      var body = row.querySelector('.vm-row-body');
      var summary = row.querySelector('.vm-row-summary');
      var nameInput = row.querySelector('.vm-name-input');

      toggleBtn.addEventListener('click', function () {
        var isOpen = !body.hidden;
        body.hidden = isOpen;
        toggleBtn.setAttribute('aria-expanded', String(!isOpen));
      });

      row.querySelector('.vm-row-remove').addEventListener('click', function () {
        row.remove();
        updateDependsOnAll();
        isDirty = true;
      });

      nameInput.addEventListener('input', function () {
        summary.textContent = this.value.trim() || 'New VM';
        updateDependsOnAll();
        isDirty = true;
      });

      row.querySelectorAll('input, select').forEach(function (el) {
        el.addEventListener('change', function () { isDirty = true; });
      });

      initScriptList(row);

      if (vmData) {
        set(row, '[name="vm_name[]"]', vmData.name);
        summary.textContent = vmData.name || 'New VM';
        set(row, '[name="vm_os[]"]', vmData.os);
        set(row, '[name="vm_vcpus[]"]', vmData.vcpus);
        set(row, '[name="vm_ram_gb[]"]', vmData.ram_gb);
        set(row, '[name="vm_disk_gb[]"]', vmData.disk_gb);
        set(row, '[name="vm_os_media[]"]', vmData.os_media);
        set(row, '[name="vm_virtio_drivers[]"]', vmData.virtio_drivers || '');
        set(row, '[name="vm_admin_username[]"]', vmData.admin_username || '');
        set(row, '[name="vm_os_config[]"]', vmData.os_config || '');
        if (vmData.automations && vmData.automations.length) {
          var scriptsList = row.querySelector('.vm-scripts-list');
          if (scriptsList) {
            vmData.automations.forEach(function (entry) {
              var scriptName = typeof entry === 'string' ? entry : entry.name;
              var rebootAfter = typeof entry === 'object' && !!entry.reboot_after;
              var savedParams = (typeof entry === 'object' && entry.parameters) ? entry.parameters : null;
              addScriptItem(scriptsList, scriptName, rebootAfter, savedParams);
            });
          }
        }
        if (vmData.depends_on && vmData.depends_on.length) {
          row.dataset.pendingDepends = vmData.depends_on.join(',');
        }
      } else {
        body.hidden = false;
        toggleBtn.setAttribute('aria-expanded', 'true');
      }

      container.appendChild(clone);
    }

    function set(row, selector, value) {
      var el = row.querySelector(selector);
      if (el && value !== undefined && value !== null) el.value = value;
    }

    function clearRows() {
      container.innerHTML = '';
      rowIdx = 0;
    }

    function getAllVmNames() {
      return Array.from(container.querySelectorAll('.vm-name-input'))
        .map(function (el) { return el.value.trim(); })
        .filter(Boolean);
    }

    function updateDependsOnAll() {
      var names = getAllVmNames();
      container.querySelectorAll('.vm-row').forEach(function (row) {
        var thisName = row.querySelector('.vm-name-input').value.trim();
        var depSel = row.querySelector('.vm-depends-on');
        if (!depSel) return;
        var selected = Array.from(depSel.selectedOptions).map(function (o) { return o.value; });
        depSel.innerHTML = '';
        names.filter(function (n) { return n !== thisName; }).forEach(function (n) {
          var opt = document.createElement('option');
          opt.value = n;
          opt.textContent = n;
          opt.selected = selected.indexOf(n) !== -1;
          depSel.appendChild(opt);
        });
      });
    }

    function applyPendingDepends() {
      container.querySelectorAll('.vm-row[data-pending-depends]').forEach(function (row) {
        var pending = row.dataset.pendingDepends.split(',').filter(Boolean);
        var depSel = row.querySelector('.vm-depends-on');
        if (!depSel) return;
        Array.from(depSel.options).forEach(function (opt) {
          opt.selected = pending.indexOf(opt.value) !== -1;
        });
        delete row.dataset.pendingDepends;
      });
    }

    function serializeDependsOn() {
      container.querySelectorAll('.vm-row').forEach(function (row) {
        var depSel = row.querySelector('.vm-depends-on');
        var hidden = row.querySelector('.vm-depends-on-hidden');
        if (depSel && hidden) {
          hidden.value = Array.from(depSel.selectedOptions)
            .map(function (o) { return o.value; })
            .join(',');
        }
      });
    }

    function serializeAutomations() {
      container.querySelectorAll('.vm-row').forEach(function (row) {
        var list = row.querySelector('.vm-scripts-list');
        var hidden = row.querySelector('.vm-automations-hidden');
        if (list && hidden) {
          var entries = Array.from(list.querySelectorAll('.script-item')).map(function (item) {
            var name = item.dataset.scriptName;
            var rebootAfter = item.querySelector('.vm-script-reboot')
              ? item.querySelector('.vm-script-reboot').checked
              : false;
            var params = {};
            item.querySelectorAll('.script-param-input').forEach(function (input) {
              if (input.value.trim()) params[input.dataset.param] = input.value.trim();
            });
            if (!rebootAfter && !Object.keys(params).length) return name;
            var entry = { name: name };
            if (rebootAfter) entry.reboot_after = true;
            if (Object.keys(params).length) entry.parameters = params;
            return entry;
          });
          hidden.value = JSON.stringify(entries);
        }
      });
    }

    function expandInvalidRows() {
      container.querySelectorAll('.vm-row').forEach(function (row) {
        var body = row.querySelector('.vm-row-body');
        var toggle = row.querySelector('.vm-row-toggle');
        if (body && body.hidden) {
          var hasEmpty = Array.from(body.querySelectorAll('[required]'))
            .some(function (inp) { return !inp.value.trim(); });
          if (hasEmpty) {
            body.hidden = false;
            if (toggle) toggle.setAttribute('aria-expanded', 'true');
          }
        }
      });
    }

    return {
      addRow: addRow,
      clearRows: clearRows,
      updateDependsOnAll: updateDependsOnAll,
      applyPendingDepends: applyPendingDepends,
      serializeDependsOn: serializeDependsOn,
      serializeAutomations: serializeAutomations,
      expandInvalidRows: expandInvalidRows,
      markDirty: function () { isDirty = true; },
      markClean: function () { isDirty = false; },
      dirty: function () { return isDirty; },
    };
  }

  return { init: init };
})();

/* Topbar — Hatch dropdown */
(function () {
  var btn = document.getElementById('hatch-dropdown-btn');
  var menu = document.getElementById('hatch-dropdown-menu');
  if (!btn || !menu) return;

  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    var open = !menu.hidden;
    menu.hidden = open;
    btn.setAttribute('aria-expanded', String(!open));
  });

  document.addEventListener('click', function () {
    if (!menu.hidden) {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !menu.hidden) {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      btn.focus();
    }
  });
})();

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
      badge.className = 'notif-badge' + (unresolvedWarningCount > 0 ? ' notif-badge--alert' : '');
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
        var warnCount = data.active_alert_count || 0;
        var lastRead = localStorage.getItem(LAST_READ_KEY) || '1970-01-01T00:00:00.000Z';
        items.forEach(function (n) {
          if (n.created_at > lastRead) showToast(n.message, n.tier);
        });
        updateBadge(items, warnCount);
        populateTray(items);
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
      if (tray.classList.contains('open')) {
        localStorage.setItem(LAST_READ_KEY, new Date().toISOString());
      }
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

  pollNotifications();
})();

/* Dropdown refresh — repopulate media/automation selects without a page reload.
   Uses event delegation so it works for dynamically-added VM row elements. */
(function () {
  var ENDPOINTS = {
    iso: '/api/media/iso',
    virtio: '/api/media/virtio',
    os_config: '/api/automation/os-config',
  };

  function rebuildOptions(select, files) {
    var prev = select.value;
    var hasEmpty = select.options.length > 0 && select.options[0].value === '';
    select.innerHTML = '';
    if (hasEmpty) {
      var empty = document.createElement('option');
      empty.value = '';
      empty.textContent = '— none —';
      select.appendChild(empty);
    }
    files.forEach(function (f) {
      var opt = document.createElement('option');
      opt.value = f;
      opt.textContent = f;
      select.appendChild(opt);
    });
    select.value = files.indexOf(prev) !== -1 ? prev : '';
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-refresh]');
    if (!btn) return;
    var endpoint = ENDPOINTS[btn.dataset.refresh];
    var formGroup = btn.closest('.form-group');
    var target = formGroup && formGroup.querySelector('select');
    if (!endpoint || !target) return;
    btn.disabled = true;
    fetch(endpoint)
      .then(function (r) { return r.json(); })
      .then(function (files) { rebuildOptions(target, files); })
      .catch(function () {})
      .finally(function () { btn.disabled = false; });
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
