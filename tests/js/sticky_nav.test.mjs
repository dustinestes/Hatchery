/**
 * Node unit tests for static/sticky_nav.js (#525).
 * Run: node --test tests/js/sticky_nav.test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const src = readFileSync(join(root, "static/sticky_nav.js"), "utf8");

function loadStickyNav() {
  const store = new Map();
  const hosts = new Map();

  function makeHost(nav, under) {
    const key = `${nav}::${under}`;
    const children = [];
    const groupClasses = new Set();
    const group = {
      classList: {
        add(name) {
          groupClasses.add(name);
        },
        remove(name) {
          groupClasses.delete(name);
        },
        contains(name) {
          return groupClasses.has(name);
        },
      },
      attrs: {},
      setAttribute(name, value) {
        this.attrs[name] = String(value);
      },
      removeAttribute(name) {
        delete this.attrs[name];
      },
      querySelector() {
        return {
          setAttribute() {},
        };
      },
      _classes: groupClasses,
    };
    const el = {
      hidden: true,
      innerHTML: "",
      attrs: {},
      getAttribute(name) {
        return this.attrs[name] || null;
      },
      setAttribute(name, value) {
        this.attrs[name] = String(value);
      },
      removeAttribute(name) {
        delete this.attrs[name];
      },
      appendChild(child) {
        children.push(child);
        this.innerHTML = "x";
      },
      closest(sel) {
        return sel === ".sidebar-item--group" ? group : null;
      },
      _children: children,
      _group: group,
    };
    hosts.set(key, el);
    return el;
  }

  makeHost("vms", "inventory");
  makeHost("nests", "connections");

  const document = {
    readyState: "complete",
    querySelector(sel) {
      const m = sel.match(
        /\.sidebar-stickies\[data-sticky-nav="([^"]+)"\]\[data-sticky-under="([^"]+)"\]/
      );
      if (!m) return null;
      return hosts.get(`${m[1]}::${m[2]}`) || null;
    },
    querySelectorAll(sel) {
      if (sel === ".sidebar-stickies") {
        return [...hosts.values()];
      }
      return [];
    },
    createElement(tag) {
      const el = {
        tagName: tag.toUpperCase(),
        className: "",
        type: "",
        href: "",
        title: "",
        textContent: "",
        innerHTML: "",
        children: [],
        attrs: {},
        setAttribute(name, value) {
          this.attrs[name] = String(value);
        },
        getAttribute(name) {
          return this.attrs[name] || null;
        },
        appendChild(child) {
          this.children.push(child);
        },
        addEventListener() {},
      };
      return el;
    },
    addEventListener() {},
  };

  const sessionStorage = {
    getItem(k) {
      return store.has(k) ? store.get(k) : null;
    },
    setItem(k, v) {
      store.set(k, String(v));
    },
  };

  const sandbox = {
    window: {},
    document,
    sessionStorage,
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.runInNewContext(src, sandbox);
  return {
    api: sandbox.hatchery.stickyNav,
    host(nav, under) {
      return hosts.get(`${nav}::${under}`);
    },
  };
}

test("truncateLabel ellipsizes long names", () => {
  const { api: nav } = loadStickyNav();
  assert.equal(nav.truncateLabel("short"), "short");
  assert.ok(nav.truncateLabel("a".repeat(40)).endsWith("…"));
  assert.ok(nav.truncateLabel("a".repeat(40)).length <= 28);
});

test("open caps at MAX_STICKIES and dismisses oldest", () => {
  const { api: nav } = loadStickyNav();
  for (let i = 0; i < nav.MAX_STICKIES + 3; i++) {
    nav.open({
      nav: "vms",
      under: "inventory",
      id: "vm-" + i,
      label: "VM " + i,
      href: "/vms/local/vm-" + i,
    });
  }
  const list = nav.list("vms", "inventory");
  assert.equal(list.length, nav.MAX_STICKIES);
  assert.equal(list[0].id, "vm-3");
  assert.equal(list[list.length - 1].id, "vm-" + (nav.MAX_STICKIES + 2));
});

test("close removes sticky by id", () => {
  const { api: nav } = loadStickyNav();
  nav.open({
    nav: "nests",
    under: "connections",
    id: "local",
    label: "Local Nest",
    href: "/nests/local",
  });
  nav.open({
    nav: "nests",
    under: "connections",
    id: "lab",
    label: "Lab",
    href: "/nests/lab",
  });
  nav.close("nests", "connections", "local");
  const list = nav.list("nests", "connections");
  assert.equal(list.length, 1);
  assert.equal(list[0].id, "lab");
});

test("open keeps parent nav group expanded while stickies exist", () => {
  const { api: nav, host } = loadStickyNav();
  const group = host("vms", "inventory")._group;
  nav.open({
    nav: "vms",
    under: "inventory",
    id: "local/dc01",
    label: "dc01",
    href: "/vms/local/dc01",
  });
  assert.equal(group.classList.contains("open"), true);
  assert.equal(group.attrs["data-sticky-keep-open"], "1");
  nav.close("vms", "inventory", "local/dc01");
  assert.equal(group.classList.contains("open"), false);
  assert.equal(group.attrs["data-sticky-keep-open"], undefined);
});

test("re-open moves sticky to end (MRU)", () => {
  const { api: nav } = loadStickyNav();
  nav.open({
    nav: "vms",
    under: "inventory",
    id: "a",
    label: "A",
    href: "/a",
  });
  nav.open({
    nav: "vms",
    under: "inventory",
    id: "b",
    label: "B",
    href: "/b",
  });
  nav.open({
    nav: "vms",
    under: "inventory",
    id: "a",
    label: "A",
    href: "/a",
  });
  const list = nav.list("vms", "inventory");
  assert.equal(list.map((x) => x.id).join(","), "b,a");
});
