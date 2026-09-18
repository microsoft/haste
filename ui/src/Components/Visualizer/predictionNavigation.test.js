// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Exercise React Router 7's REAL history listener/index implementation. Window
// listeners are registered in their actual order; a late capture listener is
// deliberately not assumed to run ahead of BrowserRouter's subscription.
import test from "node:test";
import assert from "node:assert/strict";
import { UNSAFE_createBrowserHistory as createBrowserHistory } from "react-router";
import { guardPredictionNavigation, installPredictionNavigation } from "./predictionNavigation.js";

function browserWindow() {
  const win = new EventTarget();
  let entries = [{ url: new URL("https://haste.invalid/project"), state: null }];
  let cursor = 0;
  Object.defineProperty(win, "location", { get: () => entries[cursor].url });
  win.history = {
    get state() { return entries[cursor].state; },
    get length() { return entries.length; },
    replaceState(state, _title, url) {
      entries[cursor] = { state: structuredClone(state), url: url ? new URL(url, win.location) : win.location };
    },
    pushState(state, _title, url) {
      entries = entries.slice(0, cursor + 1);
      entries.push({ state: structuredClone(state), url: new URL(url, win.location) });
      cursor++;
    },
    go(delta) {
      const next = cursor + delta;
      if (next < 0 || next >= entries.length) return;
      queueMicrotask(() => { cursor = next; win.dispatchEvent(new Event("popstate")); });
    },
    back() { this.go(-1); },
    forward() { this.go(1); },
  };
  return win;
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

function fixture(t, confirm) {
  const win = browserWindow();
  const navigator = createBrowserHistory({ window: win, v5Compat: true });
  const originalPush = navigator.push;
  const uninstall = installPredictionNavigation(navigator);
  const updates = [];
  let editorMounted = false, unmounts = 0, discards = 0;
  const unlisten = navigator.listen((update) => {
    // This is where BrowserRouter invokes its state setter. Once an away
    // update gets here, restoring the URL later cannot preserve the component.
    if (editorMounted && update.location.pathname !== "/editor") unmounts++;
    editorMounted = update.location.pathname === "/editor";
    updates.push(update);
  });
  navigator.push("/editor", { preserved: "entry state" });
  updates.length = 0;
  const editorKey = navigator.location.key;
  const unblock = guardPredictionNavigation(navigator, confirm, win, () => discards++);
  t.after(() => { unblock(); unlisten(); uninstall(); });
  return { win, navigator, updates, originalPush, uninstall, unblock, editorKey,
    mounted: () => editorMounted, unmounts: () => unmounts, discards: () => discards };
}

test("a late window listener really is too late after the Router callback", async () => {
  const win = browserWindow();
  const navigator = createBrowserHistory({ window: win, v5Compat: true });
  let mounted = true, lateObservedMounted;
  const unlisten = navigator.listen(() => { mounted = false; });
  navigator.push("/editor");
  mounted = true;
  win.addEventListener("popstate", () => { lateObservedMounted = mounted; }, true);
  win.history.back();
  await settle();
  assert.equal(lateObservedMounted, false);
  unlisten();
});

test("native Back / repeated Keep editing never delivers an away state to BrowserRouter", async (t) => {
  let prompts = 0;
  const f = fixture(t, async () => { prompts++; return false; });
  const lateObservations = [];
  f.win.addEventListener("popstate", () => lateObservations.push(f.mounted()), true);
  for (let i = 0; i < 3; i++) {
    f.win.history.back();
    await settle();
    assert.equal(f.win.location.pathname, "/editor");
    assert.equal(f.navigator.location.key, f.editorKey);
    assert.deepEqual(f.navigator.location.state, { preserved: "entry state" });
    assert.equal(f.mounted(), true);
    assert.equal(f.unmounts(), 0);
    assert.deepEqual(f.updates, []);
    assert.equal(f.win.history.length, 2);
  }
  assert.equal(prompts, 3);
  assert.ok(lateObservations.every(Boolean));
});

test("confirmed native Back delivers exactly one approved transition and preserves Forward", async (t) => {
  const f = fixture(t, async () => true);
  f.win.history.back();
  await settle();
  assert.equal(f.discards(), 1);
  assert.equal(f.unmounts(), 1);
  assert.deepEqual(f.updates.map((update) => update.location.pathname), ["/project"]);
  assert.equal(f.win.history.length, 2);
  f.unblock();
  f.win.history.forward();
  await settle();
  assert.equal(f.navigator.location.key, f.editorKey);
});

test("a pending-save blocker retains the editor across native Back and Close", async (t) => {
  const pendingSave = { active: true, requestId: "same-id", draft: { 1: "Damaged" } };
  const prompts = [];
  const f = fixture(t, async () => { prompts.push(pendingSave.active ? "Operation in progress" : "Discard"); return false; });
  for (let i = 0; i < 2; i++) {
    f.win.history.back();
    await settle();
    assert.equal(f.mounted(), true);
    assert.equal(f.unmounts(), 0);
    assert.equal(pendingSave.requestId, "same-id");
    assert.deepEqual(pendingSave.draft, { 1: "Damaged" });
  }
  assert.deepEqual(prompts, ["Operation in progress", "Operation in progress"]);
});

test("SPA push, replace and go use the same confirmation without double prompting", async (t) => {
  let approve = false, prompts = 0;
  const f = fixture(t, async () => { prompts++; return approve; });
  await f.navigator.push("/other");
  await f.navigator.replace("/other");
  await f.navigator.go(-1);
  assert.deepEqual(f.updates, []);
  approve = true;
  await f.navigator.go(-1);
  await settle();
  assert.equal(prompts, 4);
  assert.equal(f.discards(), 1);
  assert.equal(f.unmounts(), 1);
});

test("unmount cancels a pending confirmation and unload still warns", async (t) => {
  let resolve;
  const f = fixture(t, () => new Promise((done) => { resolve = done; }));
  const unload = new Event("beforeunload", { cancelable: true });
  f.win.dispatchEvent(unload);
  assert.equal(unload.defaultPrevented, true);
  const pending = f.navigator.push("/late");
  f.unblock();
  resolve(true);
  await pending;
  assert.deepEqual(f.updates, []);
});

test("late installation fails explicitly rather than falling back to a window listener", () => {
  const win = browserWindow();
  const navigator = createBrowserHistory({ window: win, v5Compat: true });
  const unlisten = navigator.listen(() => {});
  const uninstall = installPredictionNavigation(navigator);
  assert.throws(() => guardPredictionNavigation(navigator, async () => false, win), /before BrowserRouter subscribes/);
  uninstall();
  unlisten();
});
