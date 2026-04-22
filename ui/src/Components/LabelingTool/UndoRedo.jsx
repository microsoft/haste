import { useEffect, useRef } from "react";

export function useDrawingUndoRedo(drawingManager, mapRef) {
  const undoStack = useRef([]);
  const redoStack = useRef([]);
  const lastSnapshot = useRef(null);

  // Check if all shapes are closed
  const areAllShapesClosed = () => {
    const shapes = drawingManager.source.getShapes();
    return shapes.every(shape => {
      const type = shape.getType();
      // Polygons are inherently closed
      if (type === 'Polygon') return true;
      // Lines/polylines are not considered closed
      if (type === 'LineString') return false;
      // Points and other shapes can be considered closed
      return true;
    });
  };

  // Save current shapes as snapshot
  const saveSnapshot = () => {
    if (!areAllShapesClosed()) return;

    const shapes = drawingManager.source.toJson();
    const currentSnapshot = JSON.stringify(shapes);

    // Only save if different from last snapshot
    if (currentSnapshot !== lastSnapshot.current) {
      undoStack.current.push(currentSnapshot);
      redoStack.current = [];
      lastSnapshot.current = currentSnapshot;
    }
  };

  // Restore a stored topology
  const restoreSnapshot = (snapshotString) => {
    const snapshot = JSON.parse(snapshotString);
    drawingManager.source.clear();
    snapshot.features.forEach((feature) => {
      drawingManager.source.add(feature);
    });
    lastSnapshot.current = snapshotString;
  };

  // Undo action
  const undo = () => {
    if (undoStack.current.length <= 1) return;
    const currentMode = drawingManager.getOptions().mode;
    const current = undoStack.current.pop();
    redoStack.current.push(current);
    const previous = undoStack.current[undoStack.current.length - 1];
    restoreSnapshot(previous);

    // Deseleccionar todas las shapes y volver al modo anterior
    drawingManager.setOptions({ mode: 'idle' });
    setTimeout(() => {
      drawingManager.setOptions({ mode: currentMode });
    }, 0);
  };

  // Redo action
  const redo = () => {
    if (redoStack.current.length === 0) return;
    const currentMode = drawingManager.getOptions().mode;
    const snapshot = redoStack.current.pop();
    undoStack.current.push(snapshot);
    restoreSnapshot(snapshot);

    // Deseleccionar todas las shapes y volver al modo anterior
    drawingManager.setOptions({ mode: 'idle' });
    setTimeout(() => {
      drawingManager.setOptions({ mode: currentMode });
    }, 0);
  };


  // Monitor drawingManager source changes
  useEffect(() => {
    if (!drawingManager) return;

    saveSnapshot(); // Initial snapshot

    const interval = setInterval(() => {
      saveSnapshot();
    }, 500); // Check every 500ms

    return () => clearInterval(interval);
  }, [drawingManager]);

  return { undo, redo };
}
