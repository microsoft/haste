// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136 gestures, isolated from the renderer's read-only lifecycle and APIs.
export function normalizeSelectionBox(origin, end) {
  const x1 = Math.min(origin.x, end.x), x2 = Math.max(origin.x, end.x);
  const y1 = Math.min(origin.y, end.y), y2 = Math.max(origin.y, end.y);
  return x2 - x1 >= 4 && y2 - y1 >= 4 ? [[x1, y1], [x2, y2]] : null;
}

export function attachPredictionEditing(renderer, { paint, reset, boxElement, onError, canInteract = () => true, documentObject = document }) {
  const cleanups = [];
  let disposed = false;
  const detach = () => {
    if (disposed) return;
    disposed = true;
    for (const cleanup of cleanups) {
      try { cleanup(); } catch (error) { onError(error); }
    }
    if (boxElement) boxElement.style.display = "none";
  };
  const unregister = renderer.onDispose(detach);
  const safe = (action) => (...args) => {
    if (disposed) return;
    try { return action(...args); } catch (error) { onError(error); }
  };
  try {
    for (const pane of renderer.getPanes()) {
      const canvas = pane.map.getCanvasContainer();
      const interactions = { dblClickZoomInteraction: true, dragPanInteraction: true, ...pane.map.getUserInteraction() };
      const cursor = canvas.style.cursor;
      let drag = null;
      const restorePan = () => pane.map.setUserInteraction({ dragPanInteraction: interactions.dragPanInteraction });
      const cancel = () => {
        if (drag) restorePan();
        drag = null;
        if (boxElement) boxElement.style.display = "none";
      };
      const eventPixel = (event) => event.pixel || pane.map.positionsToPixels([event.position])[0];
      const click = safe((event) => {
        if (!canInteract()) return;
        if (drag) return;
        if (event.originalEvent?.ctrlKey || event.originalEvent?.metaKey) return;
        const feature = renderer.query(pane.key, eventPixel(event))[0];
        if (feature) paint([feature.id]);
      });
      const contextMenu = safe((event) => {
        if (!canInteract()) return;
        event.originalEvent?.preventDefault();
        const feature = renderer.query(pane.key, eventPixel(event))[0];
        if (feature) reset(feature.id);
        return false;
      });
      const preventMenu = (event) => event.preventDefault();
      const down = safe((event) => {
        if (!canInteract()) return;
        if (event.button !== 0 || (!event.ctrlKey && !event.metaKey)) return;
        event.preventDefault();
        event.stopPropagation();
        const rect = canvas.getBoundingClientRect();
        drag = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        pane.map.setUserInteraction({ dragPanInteraction: false });
      });
      const move = safe((event) => {
        if (!canInteract()) { cancel(); return; }
        if (!drag || !boxElement) return;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left, y = event.clientY - rect.top;
        Object.assign(boxElement.style, {
          display: "block", left: `${Math.min(drag.x, x)}px`, top: `${Math.min(drag.y, y)}px`,
          width: `${Math.abs(x - drag.x)}px`, height: `${Math.abs(y - drag.y)}px`,
        });
      });
      const up = safe((event) => {
        if (!drag) return;
        if (!canInteract()) { cancel(); return; }
        const rect = canvas.getBoundingClientRect();
        const box = normalizeSelectionBox(drag, { x: event.clientX - rect.left, y: event.clientY - rect.top });
        cancel();
        if (box) paint([...new Set(renderer.query(pane.key, box).map((feature) => feature.id))]);
      });
      const escape = (event) => { if (event.key === "Escape") cancel(); };
      const win = documentObject.defaultView;
      cleanups.push(() => {
        cancel();
        pane.map.events.remove("click", pane.fillLayer, click);
        pane.map.events.remove("contextmenu", pane.fillLayer, contextMenu);
        canvas.removeEventListener("mousedown", down, true);
        canvas.removeEventListener("contextmenu", preventMenu);
        documentObject.removeEventListener("mousemove", move);
        documentObject.removeEventListener("mouseup", up);
        documentObject.removeEventListener("keydown", escape);
        win?.removeEventListener("blur", cancel);
        pane.map.setUserInteraction({
          dblClickZoomInteraction: interactions.dblClickZoomInteraction,
          dragPanInteraction: interactions.dragPanInteraction,
        });
        canvas.style.cursor = cursor;
      });
      pane.map.setUserInteraction({ dblClickZoomInteraction: false });
      canvas.style.cursor = "pointer";
      pane.map.events.add("click", pane.fillLayer, click);
      pane.map.events.add("contextmenu", pane.fillLayer, contextMenu);
      canvas.addEventListener("mousedown", down, true);
      canvas.addEventListener("contextmenu", preventMenu);
      documentObject.addEventListener("mousemove", move);
      documentObject.addEventListener("mouseup", up);
      documentObject.addEventListener("keydown", escape);
      win?.addEventListener("blur", cancel);
    }
  } catch (error) {
    detach();
    unregister();
    throw error;
  }
  return () => { detach(); unregister(); };
}
