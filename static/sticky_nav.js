/**
 * Reusable sticky submenu items under product nav (#525 / ADR-0031).
 *
 * Stickies are dismissible entity tabs (VM under Inventory, Nest under Connections).
 * Persisted in sessionStorage; soft cap 12 per nav (oldest dismissed).
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "hatchery-sticky-nav-v1";
  var MAX_STICKIES = 12;

  function loadAll() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      var data = JSON.parse(raw);
      return data && typeof data === "object" ? data : {};
    } catch (e) {
      return {};
    }
  }

  function saveAll(data) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      /* ignore quota */
    }
  }

  function listKey(nav, under) {
    return String(nav || "") + "::" + String(under || "");
  }

  function truncateLabel(label) {
    var s = String(label || "").trim() || "Untitled";
    return s.length > 28 ? s.slice(0, 27) + "…" : s;
  }

  function hostEl(nav, under) {
    return document.querySelector(
      '.sidebar-stickies[data-sticky-nav="' +
        nav +
        '"][data-sticky-under="' +
        under +
        '"]'
    );
  }

  function getList(nav, under) {
    var all = loadAll();
    var key = listKey(nav, under);
    var list = all[key];
    return Array.isArray(list) ? list : [];
  }

  function setList(nav, under, list) {
    var all = loadAll();
    all[listKey(nav, under)] = list;
    saveAll(all);
  }

  function syncGroupOpen(host, hasStickies) {
    /* Keep the parent nav group expanded while stickies exist so they stay
       reachable after navigating to another pane. */
    if (!host || typeof host.closest !== "function") return;
    var group = host.closest(".sidebar-item--group");
    if (!group) return;
    var link = group.querySelector(":scope > .sidebar-link");
    if (hasStickies) {
      group.classList.add("open");
      group.setAttribute("data-sticky-keep-open", "1");
      if (link) link.setAttribute("aria-expanded", "true");
      return;
    }
    group.removeAttribute("data-sticky-keep-open");
    if (!group.classList.contains("active")) {
      group.classList.remove("open");
      if (link) link.setAttribute("aria-expanded", "false");
    }
  }

  function renderHost(nav, under) {
    var host = hostEl(nav, under);
    if (!host) return;
    var list = getList(nav, under);
    var activeId = host.getAttribute("data-active-id") || "";
    host.innerHTML = "";
    list.forEach(function (item) {
      var li = document.createElement("li");
      li.className =
        "sidebar-subitem sidebar-sticky-item" +
        (item.id === activeId ? " active" : "");
      li.setAttribute("data-sticky-id", item.id);

      var wrap = document.createElement("div");
      wrap.className = "sidebar-sticky-row";

      var link = document.createElement("a");
      link.className = "sidebar-sublink sidebar-sticky-link";
      link.href = item.href || "#";
      var full = String(item.label || item.id);
      link.title = full;
      link.setAttribute("aria-label", full);
      var labelSpan = document.createElement("span");
      labelSpan.className = "sidebar-label";
      labelSpan.textContent = truncateLabel(full);
      link.appendChild(labelSpan);

      var closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "sidebar-sticky-close btn-icon";
      closeBtn.title = "Dismiss " + full;
      closeBtn.setAttribute("aria-label", "Dismiss " + full);
      closeBtn.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
      closeBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closeSticky(nav, under, item.id);
      });

      wrap.appendChild(link);
      wrap.appendChild(closeBtn);
      li.appendChild(wrap);
      host.appendChild(li);
    });
    host.hidden = list.length === 0;
    syncGroupOpen(host, list.length > 0);
  }

  function renderAll() {
    document.querySelectorAll(".sidebar-stickies").forEach(function (el) {
      renderHost(el.getAttribute("data-sticky-nav"), el.getAttribute("data-sticky-under"));
    });
  }

  function openSticky(opts) {
    var nav = opts && opts.nav;
    var under = opts && opts.under;
    var id = opts && opts.id != null ? String(opts.id) : "";
    var label = (opts && opts.label) || id;
    var href = (opts && opts.href) || "#";
    if (!nav || !under || !id) return null;
    var list = getList(nav, under).filter(function (x) {
      return x.id !== id;
    });
    list.push({ id: id, label: label, href: href });
    while (list.length > MAX_STICKIES) {
      list.shift();
    }
    setList(nav, under, list);
    var host = hostEl(nav, under);
    if (host) host.setAttribute("data-active-id", id);
    renderHost(nav, under);
    return { nav: nav, under: under, id: id, label: label, href: href };
  }

  function closeSticky(nav, under, id) {
    var list = getList(nav, under).filter(function (x) {
      return x.id !== String(id);
    });
    setList(nav, under, list);
    var host = hostEl(nav, under);
    if (host && host.getAttribute("data-active-id") === String(id)) {
      host.removeAttribute("data-active-id");
    }
    renderHost(nav, under);
  }

  function activateSticky(nav, under, id) {
    var host = hostEl(nav, under);
    if (host) host.setAttribute("data-active-id", String(id || ""));
    renderHost(nav, under);
  }

  function listStickies(nav, under) {
    return getList(nav, under).slice();
  }

  global.hatchery = global.hatchery || {};
  global.hatchery.stickyNav = {
    MAX_STICKIES: MAX_STICKIES,
    open: openSticky,
    close: closeSticky,
    activate: activateSticky,
    list: listStickies,
    renderAll: renderAll,
    truncateLabel: truncateLabel,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})(typeof window !== "undefined" ? window : globalThis);
