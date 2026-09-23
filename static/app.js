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
              select.innerHTML = '<option value="">- select a script to add -</option>';
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

/**
 * Guard in-app navigation when a Clutch editor is dirty (#325).
 * Keeps native beforeunload for tab close / refresh (custom modals cannot block that).
 *
 * @param {object} opts
 * @param {function(): boolean} opts.isDirty
 * @param {function()} opts.markClean
 * @param {function()} [opts.markDirty]
 * @param {HTMLElement|null} opts.backdrop
 * @param {HTMLElement|null} opts.stayBtn
 * @param {HTMLElement|null} opts.leaveBtn
 * @param {HTMLFormElement|null} [opts.form] - clutch header fields also mark dirty
 */
hatchery.bindUnsavedLeave = function (opts) {
  var isDirty = opts.isDirty;
  var markClean = opts.markClean;
  var markDirty = opts.markDirty;
  var backdrop = opts.backdrop;
  var stayBtn = opts.stayBtn;
  var leaveBtn = opts.leaveBtn;
  var form = opts.form || null;
  if (!backdrop || !stayBtn || !leaveBtn || typeof isDirty !== 'function') return;

  var pendingHref = null;

  function closeModal() {
    backdrop.hidden = true;
    pendingHref = null;
  }

  function openModal(href) {
    pendingHref = href || null;
    backdrop.hidden = false;
    stayBtn.focus();
  }

  function navigatePending() {
    var href = pendingHref;
    markClean && markClean();
    closeModal();
    if (href) window.location.href = href;
  }

  if (form && typeof markDirty === 'function') {
    form.addEventListener('input', function (e) {
      if (e.target && e.target.closest('.vm-rows')) return;
      markDirty();
    });
    form.addEventListener('change', function (e) {
      if (e.target && e.target.closest('.vm-rows')) return;
      markDirty();
    });
  }

  document.addEventListener(
    'click',
    function (e) {
      if (!isDirty()) return;
      if (e.defaultPrevented) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest('a[href]');
      if (!a) return;
      if (a.target && a.target !== '_self') return;
      var href = a.getAttribute('href');
      if (!href || href.charAt(0) === '#') return;
      if (/^javascript:/i.test(href)) return;
      e.preventDefault();
      openModal(href);
    },
    true
  );

  stayBtn.addEventListener('click', function () {
    closeModal();
  });
  leaveBtn.addEventListener('click', function () {
    navigatePending();
  });
  backdrop.addEventListener('click', function (e) {
    if (e.target === backdrop) closeModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !backdrop.hidden) {
      e.preventDefault();
      closeModal();
    }
  });

  window.addEventListener('beforeunload', function (e) {
    if (isDirty()) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
};

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

/* Alerts — toast, bell badge, tray (umbrella Notifications group) */
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

  /** Parse alert / last-read ISO times; avoid string compare of +00:00 vs Z (#288). */
  function alertTimeMs(iso) {
    var t = Date.parse(String(iso || ''));
    return isNaN(t) ? 0 : t;
  }

  function showToast(message, tier, durationMs) {
    var container = document.getElementById('toast-container');
    if (!container) return;

    var normalized = String(tier || 'alert').toLowerCase();
    if (normalized === 'error') normalized = 'alert';
    if (normalized !== 'info' && normalized !== 'warning' && normalized !== 'alert') {
      normalized = 'alert';
    }

    var labels = { info: 'Info', warning: 'Warning', alert: 'Alert' };
    var defaults = { info: 2200, warning: 4500, alert: 5000 };

    var el = document.createElement('div');
    el.className = 'toast toast--' + normalized;
    el.setAttribute('role', normalized === 'alert' ? 'alert' : 'status');

    var icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = toastIconSvg(normalized);

    var body = document.createElement('div');
    body.className = 'toast-body';

    var tierEl = document.createElement('span');
    tierEl.className = 'toast-tier';
    tierEl.textContent = labels[normalized];

    var msgEl = document.createElement('span');
    msgEl.className = 'toast-msg';
    msgEl.textContent = message == null ? '' : String(message);

    body.appendChild(tierEl);
    body.appendChild(msgEl);
    el.appendChild(icon);
    el.appendChild(body);
    container.appendChild(el);

    var hold = typeof durationMs === 'number' ? durationMs : defaults[normalized];
    setTimeout(function () {
      el.classList.add('toast--out');
      setTimeout(function () { el.remove(); }, 320);
    }, hold);
  }

  function toastIconSvg(tier) {
    /* Simple stroke icons — info (i), warning (!), alert (x in circle) */
    if (tier === 'info') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>';
    }
    if (tier === 'warning') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
    }
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6"/><path d="M9 9l6 6"/></svg>';
  }

  /**
   * Ephemeral UI feedback only — does not create Alerts tray / DB rows.
   * showToast(message, tier?, durationMs?)
   * tier: 'info' | 'warning' | 'alert' (alias 'error' → alert). Default 'alert'.
   * durationMs: override; defaults info 2200, warning 4500, alert 5000.
   */
  hatchery.showToast = showToast;

  /**
   * Bind an Import button + hidden file input to POST multipart uploads.
   * opts: { button, input, url, acceptLabel }
   * Optional library dropdown: libraryEnabled, menu, fromFile, fromLibrary,
   *   libraryModal, libraryList, libraryEmpty, libraryStatus, libraryCancel,
   *   libraryConfirm, catalogUrl, pullUrl
   * Optional onFromLibrary(): when set, called instead of opening the modal
   *   (e.g. switch to an in-pane Library browser tab).
   * Reloads the page after any successful import. Conflicts use showToast.
   */
  hatchery.bindImportControl = function (opts) {
    var button = opts.button;
    var input = opts.input;
    var url = opts.url;
    if (!button || !input || !url) return;

    var idleLabel = button.textContent;
    var menu = opts.menu;
    var libraryEnabled = !!opts.libraryEnabled && menu;

    function closeMenu() {
      if (!menu) return;
      menu.hidden = true;
      button.setAttribute('aria-expanded', 'false');
    }

    function openMenu() {
      if (!menu) return;
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
    }

    button.addEventListener('click', function (e) {
      if (button.disabled) return;
      if (libraryEnabled) {
        e.stopPropagation();
        if (menu.hidden) openMenu();
        else closeMenu();
        return;
      }
      input.click();
    });

    if (libraryEnabled) {
      document.addEventListener('click', function () { closeMenu(); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && menu && !menu.hidden) {
          closeMenu();
          button.focus();
        }
      });
      if (opts.fromFile) {
        opts.fromFile.addEventListener('click', function () {
          closeMenu();
          input.click();
        });
      }
      if (opts.fromLibrary) {
        opts.fromLibrary.addEventListener('click', function () {
          closeMenu();
          if (typeof opts.onFromLibrary === 'function') {
            opts.onFromLibrary();
            return;
          }
          openLibraryModal();
        });
      }
    }

    function setLibraryStatus(message, ok) {
      var el = opts.libraryStatus;
      if (!el) return;
      el.textContent = message || '';
      el.classList.toggle('library-test-result--ok', ok === true);
      el.classList.toggle('library-test-result--err', ok === false);
    }

    function syncLibraryConfirm() {
      var confirm = opts.libraryConfirm;
      var list = opts.libraryList;
      if (!confirm || !list) return;
      var checked = list.querySelectorAll('input[type="checkbox"]:checked');
      confirm.disabled = checked.length === 0;
    }

    function openLibraryModal() {
      var backdrop = opts.libraryModal;
      var list = opts.libraryList;
      var empty = opts.libraryEmpty;
      var confirm = opts.libraryConfirm;
      if (!backdrop || !list || !opts.catalogUrl) {
        showToast('Library import is not available on this page.', 'warning', 4000);
        return;
      }
      list.innerHTML = '';
      if (empty) empty.hidden = true;
      if (confirm) confirm.disabled = true;
      setLibraryStatus('Loading library…', true);
      backdrop.hidden = false;
      fetch(opts.catalogUrl)
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          var items = (res.data && res.data.items) || [];
          if (!res.ok) {
            setLibraryStatus((res.data && res.data.error) || 'Failed to load library', false);
            return;
          }
          setLibraryStatus('', true);
          if (!items.length) {
            if (empty) empty.hidden = false;
            return;
          }
          items.forEach(function (item, idx) {
            var id = 'library-import-item-' + idx;
            var label = document.createElement('label');
            label.className = 'library-import-item';
            label.setAttribute('for', id);
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = id;
            cb.value = item.relative_path;
            cb.dataset.connectionId = item.connection_id || '';
            cb.dataset.name = item.name || '';
            var text = document.createElement('span');
            text.className = 'library-import-item-text';
            text.textContent = item.name +
              (item.connection_label ? (' - ' + item.connection_label) : '') +
              (item.relative_path && item.relative_path !== item.name
                ? (' (' + item.relative_path + ')')
                : '');
            label.appendChild(cb);
            label.appendChild(text);
            list.appendChild(label);
          });
          syncLibraryConfirm();
        })
        .catch(function () {
          setLibraryStatus('Network or server error', false);
        });
    }

    function closeLibraryModal() {
      if (opts.libraryModal) opts.libraryModal.hidden = true;
    }

    if (opts.libraryCancel) {
      opts.libraryCancel.addEventListener('click', closeLibraryModal);
    }
    if (opts.libraryModal) {
      opts.libraryModal.addEventListener('click', function (e) {
        if (e.target === opts.libraryModal) closeLibraryModal();
      });
    }
    if (opts.libraryList) {
      opts.libraryList.addEventListener('change', syncLibraryConfirm);
    }
    if (opts.libraryConfirm) {
      opts.libraryConfirm.addEventListener('click', function () {
        var list = opts.libraryList;
        if (!list || !opts.pullUrl) return;
        var checked = Array.prototype.slice.call(
          list.querySelectorAll('input[type="checkbox"]:checked')
        );
        if (!checked.length) return;
        opts.libraryConfirm.disabled = true;
        setLibraryStatus('Pulling…', true);
        var imported = [];
        var errors = [];
        var chain = Promise.resolve();
        checked.forEach(function (cb) {
          chain = chain.then(function () {
            return fetch(opts.pullUrl, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(Object.assign({
                connection_id: cb.dataset.connectionId,
                relative_path: cb.value,
              }, opts.pullExtra || {})),
            }).then(function (r) {
              return r.json().then(function (data) {
                return { ok: r.ok, status: r.status, data: data };
              });
            }).then(function (res) {
              if (res.ok && res.data && res.data.imported && res.data.imported.length) {
                imported = imported.concat(res.data.imported);
              } else {
                errors.push({
                  name: cb.dataset.name || cb.value,
                  reason: (res.data && res.data.error) || 'pull failed',
                });
              }
            }).catch(function () {
              errors.push({ name: cb.dataset.name || cb.value, reason: 'network error' });
            });
          });
        });
        chain.then(function () {
          errors.forEach(function (err) {
            showToast(err.name + ': ' + err.reason, 'warning', 5000);
          });
          if (imported.length) {
            var msg = imported.length === 1
              ? ('Pulled ' + imported[0])
              : ('Pulled ' + imported.length + ' scripts');
            showToast(msg + ' - ready to use.', 'info', 3200);
            closeLibraryModal();
            window.setTimeout(function () { window.location.reload(); }, 400);
            return;
          }
          setLibraryStatus(errors.length ? 'Pull finished with errors' : 'Nothing pulled', false);
          syncLibraryConfirm();
        });
      });
    }

    input.addEventListener('change', function () {
      if (!input.files || !input.files.length) return;

      var form = new FormData();
      for (var i = 0; i < input.files.length; i++) {
        form.append('files', input.files[i]);
      }

      button.disabled = true;
      button.textContent = 'Importing…';
      showToast('Import started - watch Alerts for progress on large files.', 'info', 3200);

      fetch(url, { method: 'POST', body: form })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, status: r.status, data: data };
          });
        })
        .then(function (res) {
          var data = res.data || {};
          var imported = data.imported || [];
          var errors = data.errors || [];

          errors.forEach(function (err) {
            var name = err.name || 'file';
            showToast(name + ': ' + (err.reason || 'import failed'), 'warning', 5000);
          });

          if (imported.length) {
            var msg = imported.length === 1
              ? ('Imported ' + imported[0])
              : ('Imported ' + imported.length + ' files');
            showToast(msg + ' - ready to use.', 'info', 3200);
            window.setTimeout(function () { window.location.reload(); }, 400);
            return;
          }

          if (!errors.length && data.error) {
            showToast(data.error, 'warning', 5000);
          }
        })
        .catch(function () {
          showToast('Import failed - network or server error.', 'alert', 5000);
        })
        .finally(function () {
          input.value = '';
          button.disabled = false;
          button.textContent = idleLabel;
        });
    });
  };

  /**
   * Cached | Library inventory tab strip.
   * opts: libraryEnabled, cacheTab, libTab, cachePanel, libPanel, tabsRoot,
   *   onShowLibrary (optional callback when Library tab is shown)
   * Returns { show: function(which) }
   */
  hatchery.bindInventoryTabs = function (opts) {
    var libraryEnabled = !!opts.libraryEnabled;
    var cacheTab = opts.cacheTab;
    var libTab = opts.libTab;
    var cachePanel = opts.cachePanel;
    var libPanel = opts.libPanel;

    function show(which) {
      if (!cacheTab || !cachePanel) return;
      var showLib = which === 'library';
      if (showLib && (!libraryEnabled || !libTab || libTab.disabled || !libPanel)) {
        return;
      }
      cacheTab.setAttribute('aria-selected', showLib ? 'false' : 'true');
      cacheTab.tabIndex = showLib ? -1 : 0;
      cachePanel.hidden = showLib;
      if (libTab) {
        libTab.setAttribute('aria-selected', showLib ? 'true' : 'false');
        libTab.tabIndex = (showLib && libraryEnabled) ? 0 : -1;
      }
      if (libPanel) libPanel.hidden = !showLib;
      if (showLib && typeof opts.onShowLibrary === 'function') {
        opts.onShowLibrary();
      }
    }

    if (cacheTab) {
      cacheTab.addEventListener('click', function () { show('cache'); });
    }
    if (libTab && libraryEnabled) {
      libTab.addEventListener('click', function () { show('library'); });
    }
    if (opts.tabsRoot) {
      opts.tabsRoot.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        if (!libraryEnabled || !libTab || libTab.disabled) return;
        e.preventDefault();
        var selected = opts.tabsRoot.querySelector('.inventory-tab[aria-selected="true"]');
        if (selected === cacheTab) show('library');
        else show('cache');
        var next = opts.tabsRoot.querySelector('.inventory-tab[aria-selected="true"]');
        if (next) next.focus();
      });
    }

    return { show: show };
  };

  /**
   * Wire bindLibraryBrowser from a shared id prefix (see _library_browser_panel.html).
   * opts: idPrefix, catalogUrl, pullUrl, pullExtra
   */
  hatchery.bindLibraryBrowserByPrefix = function (opts) {
    var p = opts.idPrefix;
    if (!p || !opts.catalogUrl || typeof hatchery.bindLibraryBrowser !== 'function') {
      return null;
    }
    return hatchery.bindLibraryBrowser({
      root: document.getElementById(p + '-library-browser'),
      catalogUrl: opts.catalogUrl,
      pullUrl: opts.pullUrl,
      pullExtra: opts.pullExtra || {},
      status: document.getElementById(p + '-lib-status'),
      tbody: document.getElementById(p + '-lib-tbody'),
      empty: document.getElementById(p + '-lib-empty'),
      selectAll: document.getElementById(p + '-lib-select-all'),
      pullBtn: document.getElementById(p + '-lib-pull'),
      refreshBtn: document.getElementById(p + '-lib-refresh'),
      filterQ: document.getElementById(p + '-lib-filter-q'),
      filterConn: document.getElementById(p + '-lib-filter-conn'),
      filterCached: document.getElementById(p + '-lib-filter-cached'),
      sort: document.getElementById(p + '-lib-sort'),
    });
  };

  /**
   * Shared Library re-attach modal for Cached Scripts / Clutches / Media (#364).
   * opts: reattachUrl, connections, bindings, domain, bindingNoun,
   *   getActiveItem() -> { name, relativePath } | null,
   *   mediaTarget (optional), includeTypeInConnLabel (default true)
   * Returns { open: function } or null when modal markup is absent.
   */
  hatchery.bindLibraryReattach = function (opts) {
    var backdrop = document.getElementById('library-reattach-backdrop');
    var connSel = document.getElementById('library-reattach-conn');
    var bindSel = document.getElementById('library-reattach-bind');
    var bindHint = document.getElementById('library-reattach-bind-hint');
    var pathInput = document.getElementById('library-reattach-path');
    var testBtn = document.getElementById('library-reattach-test');
    var saveBtn = document.getElementById('library-reattach-save');
    var cancelBtn = document.getElementById('library-reattach-cancel');
    var statusEl = document.getElementById('library-reattach-status');
    if (!backdrop || !connSel || !opts || !opts.reattachUrl || !opts.domain) {
      return null;
    }

    var noun = opts.bindingNoun || 'Library';
    var connections = opts.connections || [];
    var bindings = opts.bindings || [];
    var includeType = opts.includeTypeInConnLabel !== false;
    var cacheName = null;
    var tested = false;

    function basename(p) {
      var s = String(p || '').replace(/\\/g, '/');
      var i = s.lastIndexOf('/');
      return i >= 0 ? s.slice(i + 1) : s;
    }

    function setStatus(msg) {
      if (statusEl) statusEl.textContent = msg || '';
    }

    function close() {
      backdrop.hidden = true;
      cacheName = null;
      tested = false;
    }

    function bindingReady() {
      if (!bindSel || bindSel.disabled) return false;
      return !!(bindSel.value || '').trim();
    }

    function noBindingMessage() {
      return 'Add a ' + noun + ' binding under Settings → Library for this connection first';
    }

    function refreshBindings() {
      if (!bindSel) return;
      var cid = connSel.value;
      var matches = bindings.filter(function (b) {
        return b.connection_id === cid;
      });
      bindSel.innerHTML = '';
      if (!matches.length) {
        var empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'No bindings on this connection';
        bindSel.appendChild(empty);
        bindSel.disabled = true;
        if (bindHint) {
          bindHint.textContent =
            noBindingMessage() + '. Re-attach always requires a binding.';
        }
      } else {
        bindSel.disabled = false;
        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select a binding';
        bindSel.appendChild(placeholder);
        matches.forEach(function (b) {
          var opt = document.createElement('option');
          opt.value = b.id;
          opt.textContent = (b.filter || '*') + (b.enabled === false ? ' (off)' : '');
          bindSel.appendChild(opt);
        });
        if (matches.length === 1) {
          bindSel.value = matches[0].id;
        }
        if (bindHint) {
          bindHint.textContent =
            'Required so binding remove can cascade-delete this Cached file.';
        }
      }
      tested = false;
      if (saveBtn) saveBtn.disabled = true;
    }

    function lockedRelativePath(name, preferred) {
      var preferredBn = basename(preferred);
      var nameBn = basename(name);
      if (preferred && preferredBn === nameBn) {
        return String(preferred).replace(/\\/g, '/');
      }
      return nameBn;
    }

    function open() {
      if (typeof opts.getActiveItem !== 'function') return;
      var item = opts.getActiveItem();
      if (!item || !item.name) return;
      cacheName = item.name;
      if (pathInput) {
        pathInput.value = lockedRelativePath(item.name, item.relativePath);
        pathInput.disabled = true;
        pathInput.readOnly = true;
      }
      setStatus('');
      if (saveBtn) saveBtn.disabled = true;
      tested = false;
      refreshBindings();
      backdrop.hidden = false;
      connSel.focus();
    }

    function body(commit) {
      var payload = {
        domain: opts.domain,
        name: cacheName,
        connection_id: connSel.value,
        relative_path: pathInput ? (pathInput.value || '').trim() : '',
        commit: !!commit,
      };
      if (opts.mediaTarget) {
        payload.media_target = opts.mediaTarget;
      }
      var bid = bindSel && !bindSel.disabled ? (bindSel.value || '').trim() : '';
      if (bid) payload.binding_id = bid;
      return payload;
    }

    connSel.innerHTML = '';
    connections.forEach(function (c) {
      var opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = includeType
        ? (c.label || c.id) + ' (' + (c.type || '') + ')'
        : (c.label || c.id);
      connSel.appendChild(opt);
    });
    connSel.addEventListener('change', refreshBindings);
    if (bindSel) {
      bindSel.addEventListener('change', function () {
        tested = false;
        if (saveBtn) saveBtn.disabled = true;
      });
    }
    if (cancelBtn) cancelBtn.addEventListener('click', close);
    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop) close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !backdrop.hidden) {
        e.preventDefault();
        close();
      }
    });

    if (testBtn) {
      testBtn.addEventListener('click', function () {
        if (!cacheName || !opts.reattachUrl) return;
        if (!bindingReady()) {
          setStatus(
            bindSel && bindSel.disabled
              ? noBindingMessage()
              : 'Select a Library binding first'
          );
          if (saveBtn) saveBtn.disabled = true;
          return;
        }
        fetch(opts.reattachUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body(false)),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function (res) {
            if (!res.ok) {
              setStatus((res.data && res.data.error) || 'Test failed');
              if (saveBtn) saveBtn.disabled = true;
              tested = false;
              return;
            }
            setStatus(
              'Path resolves (' + (res.data.source_digest_kind || 'tip') + ')'
            );
            tested = true;
            if (saveBtn) saveBtn.disabled = !bindingReady();
          });
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        if (!cacheName || !opts.reattachUrl) return;
        if (!bindingReady()) {
          setStatus(
            bindSel && bindSel.disabled
              ? noBindingMessage()
              : 'Select a Library binding first'
          );
          return;
        }
        if (!tested) {
          setStatus('Test the path before re-attaching');
          return;
        }
        fetch(opts.reattachUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body(true)),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function (res) {
            if (!res.ok) {
              setStatus((res.data && res.data.error) || 'Re-attach failed');
              return;
            }
            window.location.reload();
          });
      });
    }

    refreshBindings();
    return { open: open, close: close };
  };

  /**
   * In-pane Library catalog browser (filter / sort / batch pull).
   * opts: root, catalogUrl, pullUrl, status, tbody, empty, selectAll, pullBtn,
   *   refreshBtn, filterQ, filterConn, filterCached, sort,
   *   pullExtra (optional object merged into each pull POST body)
   * Returns { load: function }
   */
  hatchery.bindLibraryBrowser = function (opts) {
    var items = [];
    var selected = {};
    var loaded = false;
    var COPY_SVG =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>' +
      '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
      '</svg>';

    function setStatus(message, ok) {
      var el = opts.status;
      if (!el) return;
      el.textContent = message || '';
      el.classList.toggle('library-test-result--ok', ok === true);
      el.classList.toggle('library-test-result--err', ok === false);
    }

    function esc(str) {
      return String(str == null ? '' : str).replace(/[&<>"']/g, function (c) {
        return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
      });
    }

    function copySha(sha) {
      if (!sha) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(sha).then(function () {
          showToast('SHA-256 copied', 'info', 2200);
        }).catch(function () {
          showToast('Could not copy SHA-256', 'warning', 3200);
        });
      } else {
        showToast('Could not copy SHA-256', 'warning', 3200);
      }
    }

    function fillConnectionFilter(rows) {
      var sel = opts.filterConn;
      if (!sel) return;
      var current = sel.value;
      var labels = {};
      rows.forEach(function (row) {
        var id = row.connection_id || '';
        var label = row.connection_label || id;
        if (id) labels[id] = label;
      });
      sel.innerHTML = '<option value="">All connections</option>';
      Object.keys(labels).sort(function (a, b) {
        return labels[a].localeCompare(labels[b], undefined, { sensitivity: 'base' });
      }).forEach(function (id) {
        var opt = document.createElement('option');
        opt.value = id;
        opt.textContent = labels[id];
        sel.appendChild(opt);
      });
      if (current && labels[current]) sel.value = current;
    }

    function filteredSorted() {
      var q = ((opts.filterQ && opts.filterQ.value) || '').trim().toLowerCase();
      var conn = (opts.filterConn && opts.filterConn.value) || '';
      var cached = (opts.filterCached && opts.filterCached.value) || '';
      var sortKey = (opts.sort && opts.sort.value) || 'name';
      var rows = items.filter(function (row) {
        if (conn && row.connection_id !== conn) return false;
        if (cached === 'yes' && !row.cached) return false;
        if (cached === 'no' && row.cached) return false;
        if (q) {
          var hay = [
            row.name || '',
            row.relative_path || '',
            row.connection_label || '',
          ].join(' ').toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        return true;
      });
      rows.sort(function (a, b) {
        var av;
        var bv;
        if (sortKey === 'connection') {
          av = (a.connection_label || a.connection_id || '').toLowerCase();
          bv = (b.connection_label || b.connection_id || '').toLowerCase();
        } else if (sortKey === 'path') {
          av = (a.relative_path || '').toLowerCase();
          bv = (b.relative_path || '').toLowerCase();
        } else {
          av = (a.name || '').toLowerCase();
          bv = (b.name || '').toLowerCase();
        }
        if (av < bv) return -1;
        if (av > bv) return 1;
        return (a.relative_path || '').localeCompare(b.relative_path || '');
      });
      return rows;
    }

    function rowKey(row) {
      return (row.connection_id || '') + '\0' + (row.relative_path || row.name || '');
    }

    function syncPullBtn() {
      if (!opts.pullBtn) return;
      opts.pullBtn.disabled = Object.keys(selected).length === 0;
    }

    function syncSelectAll(visible) {
      if (!opts.selectAll) return;
      if (!visible.length) {
        opts.selectAll.checked = false;
        opts.selectAll.indeterminate = false;
        return;
      }
      var n = 0;
      visible.forEach(function (row) {
        if (selected[rowKey(row)]) n += 1;
      });
      opts.selectAll.checked = n === visible.length;
      opts.selectAll.indeterminate = n > 0 && n < visible.length;
    }

    function render() {
      var tbody = opts.tbody;
      if (!tbody) return;
      var rows = filteredSorted();
      tbody.innerHTML = '';
      if (opts.empty) opts.empty.hidden = rows.length > 0 || !loaded;
      rows.forEach(function (row, idx) {
        var key = rowKey(row);
        var id = 'lib-browser-row-' + idx;
        var tr = document.createElement('tr');
        var name = row.name || '';
        var path = row.relative_path || '';
        var showPath = path && path !== name;
        var statusText = row.cached ? 'Cached' : 'Library only';
        var statusClass = row.cached
          ? 'library-browser-status-badge library-browser-status-badge--cached'
          : 'library-browser-status-badge library-browser-status-badge--remote';
        var sha = row.sha256 ? String(row.sha256) : '';
        var shaCell = sha
          ? ('<button type="button" class="library-browser-sha-btn" ' +
             'aria-label="Copy SHA-256 for ' + esc(name || path || 'item') + '" ' +
             'title="Copy SHA-256">' + COPY_SVG + '</button>')
          : '<span class="library-browser-sha-empty" title="SHA-256 unknown">—</span>';
        tr.innerHTML =
          '<td class="library-browser-check-col">' +
            '<input type="checkbox" id="' + id + '"' +
            (selected[key] ? ' checked' : '') +
            ' aria-label="Select ' + esc(name || path || 'item') + '">' +
          '</td>' +
          '<td class="library-browser-name-cell">' +
            '<div class="library-browser-item">' +
              '<span class="scripts-nav-label">' + esc(name) + '</span>' +
              (showPath
                ? ('<span class="scripts-nav-sub" title="' + esc(path) + '">' + esc(path) + '</span>')
                : '') +
            '</div>' +
          '</td>' +
          '<td>' + esc(row.connection_label || row.connection_id || '') + '</td>' +
          '<td class="library-browser-sha-col">' + shaCell + '</td>' +
          '<td><span class="' + statusClass + '">' + esc(statusText) + '</span></td>';
        var cb = tr.querySelector('input[type="checkbox"]');
        cb.addEventListener('change', function () {
          if (cb.checked) selected[key] = row;
          else delete selected[key];
          syncPullBtn();
          syncSelectAll(rows);
        });
        var shaBtn = tr.querySelector('.library-browser-sha-btn');
        if (shaBtn) {
          shaBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            copySha(sha);
          });
        }
        tbody.appendChild(tr);
      });
      syncSelectAll(rows);
      syncPullBtn();
      if (opts.status && loaded && !opts.status.classList.contains('library-test-result--err')) {
        var total = items.length;
        var shown = rows.length;
        setStatus(
          shown === total
            ? (total + ' catalog hit' + (total === 1 ? '' : 's'))
            : (shown + ' of ' + total + ' hits'),
          true
        );
      }
    }

    function load() {
      if (!opts.catalogUrl) return;
      setStatus('Loading library…', true);
      if (opts.pullBtn) opts.pullBtn.disabled = true;
      fetch(opts.catalogUrl)
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          loaded = true;
          if (!res.ok) {
            items = [];
            selected = {};
            setStatus((res.data && res.data.error) || 'Failed to load library', false);
            render();
            return;
          }
          items = (res.data && res.data.items) || [];
          fillConnectionFilter(items);
          var nextSelected = {};
          Object.keys(selected).forEach(function (key) {
            var match = items.find(function (row) { return rowKey(row) === key; });
            if (match) nextSelected[key] = match;
          });
          selected = nextSelected;
          setStatus('', true);
          render();
        })
        .catch(function () {
          loaded = true;
          items = [];
          selected = {};
          setStatus('Network or server error', false);
          render();
        });
    }

    function pullSelected() {
      var keys = Object.keys(selected);
      if (!keys.length || !opts.pullUrl) return;
      if (opts.pullBtn) opts.pullBtn.disabled = true;
      setStatus('Pulling…', true);
      var imported = [];
      var errors = [];
      var chain = Promise.resolve();
      keys.forEach(function (key) {
        var row = selected[key];
        chain = chain.then(function () {
          return fetch(opts.pullUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(Object.assign({
              connection_id: row.connection_id,
              relative_path: row.relative_path,
              binding_id: row.binding_id || undefined,
            }, opts.pullExtra || {})),
          }).then(function (r) {
            return r.json().then(function (data) {
              return { ok: r.ok, data: data };
            });
          }).then(function (res) {
            if (res.ok && res.data && res.data.imported && res.data.imported.length) {
              imported = imported.concat(res.data.imported);
            } else {
              errors.push({
                name: row.name || row.relative_path,
                reason: (res.data && res.data.error) || 'pull failed',
              });
            }
          }).catch(function () {
            errors.push({ name: row.name || row.relative_path, reason: 'network error' });
          });
        });
      });
      chain.then(function () {
        errors.forEach(function (err) {
          showToast(err.name + ': ' + err.reason, 'warning', 5000);
        });
        if (imported.length) {
          var msg = imported.length === 1
            ? ('Pulled ' + imported[0])
            : ('Pulled ' + imported.length + ' items');
          showToast(msg + ' - ready to use.', 'info', 3200);
          window.setTimeout(function () { window.location.reload(); }, 400);
          return;
        }
        setStatus(errors.length ? 'Pull finished with errors' : 'Nothing pulled', false);
        syncPullBtn();
      });
    }

    if (opts.refreshBtn) {
      opts.refreshBtn.addEventListener('click', load);
    }
    if (opts.pullBtn) {
      opts.pullBtn.addEventListener('click', pullSelected);
    }
    if (opts.selectAll) {
      opts.selectAll.addEventListener('change', function () {
        var rows = filteredSorted();
        if (opts.selectAll.checked) {
          rows.forEach(function (row) { selected[rowKey(row)] = row; });
        } else {
          rows.forEach(function (row) { delete selected[rowKey(row)]; });
        }
        render();
      });
    }
    ['filterQ', 'filterConn', 'filterCached', 'sort'].forEach(function (key) {
      var el = opts[key];
      if (!el) return;
      var evt = el.tagName === 'INPUT' ? 'input' : 'change';
      el.addEventListener(evt, render);
    });

    return { load: load };
  };

  function updateBadge(items) {
    var badge = document.getElementById('notif-badge');
    if (!badge) return;
    var lastReadMs = alertTimeMs(localStorage.getItem(LAST_READ_KEY) || '1970-01-01T00:00:00.000Z');
    var hasUnseen = (items || []).some(function (n) {
      return !n.resolved && alertTimeMs(n.created_at) > lastReadMs;
    });
    if (hasUnseen) {
      badge.textContent = '';
      badge.setAttribute('aria-label', 'New alerts');
      badge.style.display = 'flex';
      badge.className = 'notif-badge notif-badge--alert notif-badge--dot';
    } else {
      badge.style.display = 'none';
      badge.textContent = '';
      badge.removeAttribute('aria-label');
      badge.className = 'notif-badge';
    }
  }

  function populateTray(items) {
    var list = document.getElementById('notif-tray-list');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="notif-tray-empty">No recent alerts</div>';
      return;
    }
    list.innerHTML = items.slice(0, 5).map(function (n) {
      var tier = String(n.tier || 'alert').toLowerCase();
      if (tier === 'error') tier = 'alert';
      if (tier !== 'info' && tier !== 'warning' && tier !== 'alert') tier = 'alert';
      return '<div class="notif-tray-item">' +
        '<div class="notif-tray-meta">' +
        '<span class="notif-tier-badge notif-tier-badge--' + tier + '">' + tier + '</span>' +
        '<span class="notif-tray-time">' + timeAgo(n.created_at) + '</span>' +
        '</div>' +
        '<div class="notif-tray-msg">' + escapeHtml(n.message) + '</div>' +
        '</div>';
    }).join('');
  }

  /* Persist toasted alert incarnations across navigations (#278 / #288).
     Store id → created_at so wiping hatchery.db (id reuse) still toasts. */
  var TOASTED_KEY = 'hatchery-toasted-alert-ids';
  var lastAlertItems = [];

  function loadToastedMap() {
    try {
      var raw = JSON.parse(localStorage.getItem(TOASTED_KEY) || '{}');
      var map = {};
      if (Array.isArray(raw)) {
        // Legacy format: bare ids — treat as unknown created_at.
        raw.forEach(function (id) {
          map[String(id)] = '*';
        });
        return map;
      }
      if (raw && typeof raw === 'object') {
        Object.keys(raw).forEach(function (id) {
          map[String(id)] = String(raw[id]);
        });
      }
      return map;
    } catch (e) {
      return {};
    }
  }

  function saveToastedMap(map) {
    var ids = Object.keys(map);
    if (ids.length > 200) {
      ids = ids.slice(ids.length - 200);
      var trimmed = {};
      ids.forEach(function (id) { trimmed[id] = map[id]; });
      map = trimmed;
    }
    try {
      localStorage.setItem(TOASTED_KEY, JSON.stringify(map));
    } catch (e) { /* ignore quota */ }
  }

  function pollAlerts() {
    return fetch('/api/alerts')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var items = data.items || [];
        var lastReadMs = alertTimeMs(localStorage.getItem(LAST_READ_KEY) || '1970-01-01T00:00:00.000Z');
        var toasted = loadToastedMap();
        items.forEach(function (n) {
          var id = String(n.id);
          var created = String(n.created_at || '');
          var prev = toasted[id];
          // Same row already handled (nav / next poll).
          if (prev && prev === created) return;

          var idReused = !!(prev && prev !== '*' && prev !== created);
          toasted[id] = created || '*';

          if (n.resolved) return;

          // Toast new unresolved rows, or the same sqlite id after a DB wipe.
          if (idReused || alertTimeMs(created) > lastReadMs) {
            showToast(n.message, n.tier || 'alert');
          }
        });
        saveToastedMap(toasted);
        lastAlertItems = items;
        updateBadge(items);
        populateTray(items);
        return data;
      })
      .catch(function () { return null; });
  }

  function applyPlaneStatus(status) {
    function apply(id, title, dot, visible) {
      var el = document.getElementById(id);
      if (!el) return;
      if (typeof visible === 'boolean') {
        el.hidden = !visible;
      }
      var safeDot = (dot === 'red' || dot === 'green' || dot === 'muted') ? dot : 'muted';
      el.title = title || '';
      el.setAttribute('data-dot', safeDot);
      var dotEl = el.querySelector('.nest-status-dot');
      if (dotEl) {
        dotEl.className = 'nest-status-dot nest-status-dot--' + safeDot;
      }
      var sr = document.getElementById(id + '-sr');
      if (sr) sr.textContent = title || '';
    }
    apply('footer-hatchery', status.hatchery_title, status.hatchery_dot);
    apply('footer-nests', status.nests_title, status.nests_dot);
    apply(
      'footer-libraries',
      status.libraries_title,
      status.libraries_dot,
      !!status.libraries_visible
    );
  }

  function pollPlaneStatus() {
    return fetch('/api/plane-status')
      .then(function (r) { return r.json(); })
      .then(function (status) {
        applyPlaneStatus(status);
        return status;
      })
      .catch(function () { return null; });
  }

  var STATUS_POLL_MS = 15000;
  var statusTickListeners = [];

  /**
   * Status surfaces bus (#282): one refresh entrypoint for bell / tray / footer
   * (Hatchery, Nests, Libraries). Surfaces read stored health — they do not re-run checks.
   * Pane code may subscribe via hatchery.onStatusTick instead of a new setInterval.
   */
  function notifyStatusTick(payload) {
    statusTickListeners.slice().forEach(function (fn) {
      try {
        fn(payload);
      } catch (e) { /* listener errors must not break the bus */ }
    });
  }

  function refreshStatusSurfaces() {
    return Promise.all([pollAlerts(), pollPlaneStatus()]).then(function (parts) {
      var payload = { alerts: parts[0], planeStatus: parts[1] };
      notifyStatusTick(payload);
      return payload;
    });
  }

  function onStatusTick(fn) {
    if (typeof fn !== 'function') {
      return function () {};
    }
    statusTickListeners.push(fn);
    return function offStatusTick() {
      var i = statusTickListeners.indexOf(fn);
      if (i >= 0) statusTickListeners.splice(i, 1);
    };
  }

  hatchery.refreshStatusSurfaces = refreshStatusSurfaces;
  hatchery.onStatusTick = onStatusTick;

  /* Bell tray toggle */
  var bellBtn = document.getElementById('notif-bell');
  var tray = document.getElementById('notif-tray');
  if (bellBtn && tray) {
    bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      tray.classList.toggle('open');
      if (tray.classList.contains('open')) {
        localStorage.setItem(LAST_READ_KEY, new Date().toISOString());
        updateBadge(lastAlertItems);
      }
    });
    document.addEventListener('click', function (e) {
      if (tray.classList.contains('open') && !tray.contains(e.target) && e.target !== bellBtn) {
        tray.classList.remove('open');
      }
    });
  }

  refreshStatusSurfaces();
  setInterval(refreshStatusSurfaces, STATUS_POLL_MS);
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
      empty.textContent = '- none -';
      select.appendChild(empty);
    }
    var names = (files || []).map(function (f) {
      return (f && typeof f === 'object') ? f.name : f;
    }).filter(Boolean);
    names.forEach(function (name) {
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
    select.value = names.indexOf(prev) !== -1 ? prev : '';
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

/* Sidebar collapse toggle + collapsed-group flyouts */
(function () {
  var sidebar = document.getElementById('sidebar');
  var btn = document.getElementById('sidebar-toggle');
  if (!sidebar || !btn) return;

  var nav = sidebar.querySelector('.sidebar-nav');
  var leaveTimer = null;
  var VIEWPORT_PAD = 8;
  var scrollHideTimer = null;
  var scrollThumb = document.createElement('div');
  scrollThumb.className = 'sidebar-scroll-thumb';
  scrollThumb.setAttribute('aria-hidden', 'true');
  sidebar.appendChild(scrollThumb);

  function hideScrollThumb() {
    scrollThumb.classList.remove('is-visible');
  }

  /* Apply saved state (suppress transition on init, then re-enable) */
  if (localStorage.getItem('hatchery-sidebar-collapsed') === 'true') {
    sidebar.classList.add('collapsed');
  }
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      document.documentElement.classList.remove('sidebar-collapsed-init');
    });
  });

  function resetFlyoutStyles(sub) {
    if (!sub) return;
    sub.style.left = '';
    sub.style.top = '';
    sub.style.maxHeight = '';
    sub.style.overflowY = '';
  }

  function positionFlyout(group) {
    var link = group.querySelector(':scope > .sidebar-link');
    var sub = group.querySelector(':scope > .sidebar-subnav');
    if (!link || !sub) return;

    var rect = link.getBoundingClientRect();
    sub.style.left = Math.round(rect.right - 4) + 'px';
    sub.style.top = Math.round(rect.top) + 'px';
    sub.style.maxHeight = '';
    sub.style.overflowY = '';

    var h = sub.offsetHeight;
    var maxH = window.innerHeight - VIEWPORT_PAD * 2;
    var top = rect.top;

    if (h > maxH) {
      sub.style.maxHeight = maxH + 'px';
      sub.style.overflowY = 'auto';
      top = VIEWPORT_PAD;
    } else if (top + h > window.innerHeight - VIEWPORT_PAD) {
      top = Math.max(VIEWPORT_PAD, window.innerHeight - VIEWPORT_PAD - h);
    }

    sub.style.top = Math.round(top) + 'px';
  }

  function clearFlyouts() {
    clearTimeout(leaveTimer);
    leaveTimer = null;
    sidebar.querySelectorAll('.sidebar-item--group.flyout-open').forEach(function (el) {
      el.classList.remove('flyout-open');
      resetFlyoutStyles(el.querySelector(':scope > .sidebar-subnav'));
      var link = el.querySelector(':scope > .sidebar-link');
      if (link) link.setAttribute('aria-expanded', el.classList.contains('open') ? 'true' : 'false');
    });
  }

  function openFlyout(group) {
    clearTimeout(leaveTimer);
    leaveTimer = null;
    sidebar.querySelectorAll('.sidebar-item--group.flyout-open').forEach(function (el) {
      if (el === group) return;
      el.classList.remove('flyout-open');
      resetFlyoutStyles(el.querySelector(':scope > .sidebar-subnav'));
      var otherLink = el.querySelector(':scope > .sidebar-link');
      if (otherLink) otherLink.setAttribute('aria-expanded', el.classList.contains('open') ? 'true' : 'false');
    });
    group.classList.add('flyout-open');
    var link = group.querySelector(':scope > .sidebar-link');
    if (link) link.setAttribute('aria-expanded', 'true');
    positionFlyout(group);
  }

  function scheduleClose(group) {
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(function () {
      if (!group.classList.contains('flyout-open')) return;
      group.classList.remove('flyout-open');
      resetFlyoutStyles(group.querySelector(':scope > .sidebar-subnav'));
      var link = group.querySelector(':scope > .sidebar-link');
      if (link) link.setAttribute('aria-expanded', group.classList.contains('open') ? 'true' : 'false');
    }, 160);
  }

  btn.addEventListener('click', function () {
    var collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('hatchery-sidebar-collapsed', collapsed);
    btn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    btn.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    clearFlyouts();
    hideScrollThumb();
  });

  /* Hover / focus open the flyout when collapsed. */
  sidebar.querySelectorAll('.sidebar-item--group').forEach(function (group) {
    group.addEventListener('mouseenter', function () {
      if (!sidebar.classList.contains('collapsed')) return;
      openFlyout(group);
    });
    group.addEventListener('mouseleave', function () {
      if (!sidebar.classList.contains('collapsed')) return;
      scheduleClose(group);
    });
    group.addEventListener('focusin', function () {
      if (!sidebar.classList.contains('collapsed')) return;
      openFlyout(group);
    });
    group.addEventListener('focusout', function (e) {
      if (!sidebar.classList.contains('collapsed')) return;
      if (e.relatedTarget && group.contains(e.relatedTarget)) return;
      scheduleClose(group);
    });
  });

  /* Click toggles flyout for touch; prevents navigating away before a choice. */
  sidebar.addEventListener('click', function (e) {
    var groupLink = e.target.closest('.sidebar-item--group > .sidebar-link');
    if (!groupLink || !sidebar.classList.contains('collapsed')) return;
    var group = groupLink.closest('.sidebar-item--group');
    if (!group) return;
    e.preventDefault();
    if (group.classList.contains('flyout-open')) {
      clearFlyouts();
    } else {
      openFlyout(group);
    }
  });

  document.addEventListener('click', function (e) {
    if (!sidebar.classList.contains('collapsed')) return;
    if (e.target.closest('.sidebar-item--group')) return;
    clearFlyouts();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') clearFlyouts();
  });

  function repositionOpenFlyouts() {
    if (!sidebar.classList.contains('collapsed')) return;
    sidebar.querySelectorAll('.sidebar-item--group.flyout-open').forEach(positionFlyout);
  }

  window.addEventListener('resize', repositionOpenFlyouts);

  function updateScrollThumb() {
    if (!nav || !sidebar.classList.contains('collapsed')) {
      hideScrollThumb();
      return;
    }
    var overflow = nav.scrollHeight - nav.clientHeight;
    if (overflow <= 0) {
      hideScrollThumb();
      return;
    }
    var trackH = nav.clientHeight;
    var thumbH = Math.max(20, Math.round((nav.clientHeight / nav.scrollHeight) * trackH));
    var maxTop = trackH - thumbH;
    var top = maxTop <= 0 ? 0 : (nav.scrollTop / overflow) * maxTop;
    var navRect = nav.getBoundingClientRect();
    var sideRect = sidebar.getBoundingClientRect();
    scrollThumb.style.height = thumbH + 'px';
    scrollThumb.style.transform =
      'translateY(' + Math.round(navRect.top - sideRect.top + top) + 'px)';
    scrollThumb.classList.add('is-visible');
  }

  if (nav) {
    nav.addEventListener('scroll', function () {
      repositionOpenFlyouts();
      updateScrollThumb();
      clearTimeout(scrollHideTimer);
      scrollHideTimer = setTimeout(hideScrollThumb, 900);
    });
  }
})();
