// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// React Router 7 BrowserRouter calls navigator.listen(setState) in its layout
// effect. Intercept that subscription BEFORE it exists, not a later Window
// popstate listener: once setState sees the away location the editor can unmount.
const channels = new WeakMap();

export function installPredictionNavigation(navigator) {
  if (channels.has(navigator)) throw new Error("Prediction navigation is already installed.");
  const originals = Object.fromEntries(["listen", "push", "replace", "go"].map((name) => [name, navigator[name]]));
  if (Object.values(originals).some((method) => typeof method !== "function")) {
    throw new Error("Prediction navigation requires BrowserRouter's history interface.");
  }
  let owner = null;
  let subscribed = false;
  let disposed = false;
  let asking = false;
  let restoring = null;
  let approvedPop = false;
  const ask = async (blocker, proceed) => {
    if (asking || !blocker.active || disposed) return;
    asking = true;
    try {
      if (await blocker.confirm() && blocker.active && !disposed) {
        blocker.beforeNavigate();
        proceed();
      }
    } finally { asking = false; }
  };
  const dispatch = (update, notifyRouter) => {
    if (disposed) { notifyRouter(update); return; }
    if (restoring && update.action === "POP") {
      const transaction = restoring;
      restoring = null;
      // The original history object has restored its own index. Withhold this
      // notification too: the Router never left the editor in the first place.
      void ask(transaction.owner, () => {
        approvedPop = true;
        originals.go.call(navigator, transaction.delta);
      });
      return;
    }
    if (approvedPop && update.action === "POP") {
      approvedPop = false;
      notifyRouter(update);
      return;
    }
    if (owner?.active && update.action === "POP") {
      const blocker = owner;
      if (Number.isInteger(update.delta) && update.delta !== 0) {
        restoring = { owner: blocker, delta: update.delta };
        // Native traversals cannot be cancelled. Restore the EXACT entry via
        // history.go, retaining keys/state/forward history, while the Router
        // notification is blocked. Never push/replace a compensating URL.
        originals.go.call(navigator, -update.delta);
      } else {
        // Non-indexed same-document entries cannot be reversed safely. Retain
        // the mounted editor and require approval before notifying the Router.
        void ask(blocker, () => notifyRouter(update));
      }
      return;
    }
    notifyRouter(update);
  };
  const wrappers = {
    listen(notifyRouter) {
      const unlisten = originals.listen.call(navigator, (update) => dispatch(update, notifyRouter));
      subscribed = true;
      return () => { subscribed = false; unlisten(); };
    },
  };
  for (const name of ["push", "replace", "go"]) {
    wrappers[name] = (...args) => {
      if (!owner?.active) return originals[name].apply(navigator, args);
      return ask(owner, () => {
        if (name === "go") approvedPop = true;
        originals[name].apply(navigator, args);
      });
    };
  }
  Object.assign(navigator, wrappers);
  const channel = {
    block(blocker) {
      if (!subscribed) {
        throw new Error("Prediction navigation must be installed before BrowserRouter subscribes.");
      }
      if (owner?.active) throw new Error("Only one prediction editor can guard navigation.");
      owner = blocker;
      return () => {
        blocker.active = false;
        if (owner === blocker) owner = null;
      };
    },
  };
  channels.set(navigator, channel);
  return () => {
    disposed = true;
    if (owner) owner.active = false;
    for (const name of Object.keys(originals)) {
      if (navigator[name] === wrappers[name]) navigator[name] = originals[name];
    }
    channels.delete(navigator);
  };
}

export function guardPredictionNavigation(navigator, confirm, win = window, beforeNavigate = () => {}) {
  const channel = channels.get(navigator);
  if (!channel) throw new Error("Mount PredictionNavigationBridge inside BrowserRouter before using the editor.");
  const unblock = channel.block({ active: true, confirm, beforeNavigate });
  const beforeUnload = (event) => { event.preventDefault(); event.returnValue = ""; };
  win.addEventListener("beforeunload", beforeUnload);
  return () => {
    unblock();
    win.removeEventListener("beforeunload", beforeUnload);
  };
}
