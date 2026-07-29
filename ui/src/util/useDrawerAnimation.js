// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useRef, useState } from "react";

// Drives the slide-in / slide-out animation for a FluentUI OverlayDrawer that
// is mounted conditionally by its parent (the common HASTE pattern where a
// parent renders `{visible && <SomeDrawer onClose=... />}`).
//
// FluentUI only plays the drawer motion when the `open` prop transitions while
// the component stays mounted. Mounting straight with `open={true}` skips the
// enter animation, and unmounting immediately on close skips the exit
// animation ("it just disappears"). This hook fixes both:
//   1. start closed and flip to open right after mount, so the enter motion
//      always plays;
//   2. on close, set open=false to play the exit motion, then notify the
//      parent (which unmounts us) after the motion finishes.
//
// Usage:
//   const { open, requestClose } = useDrawerAnimation(onClose);
//   <OverlayDrawer open={open} onOpenChange={(_, d) => { if (!d.open) requestClose(); }}>
//   ... and wire close buttons to requestClose instead of onClose.
export function useDrawerAnimation(onClose, duration = 250) {
  const [open, setOpen] = useState(false);
  const closingRef = useRef(false);

  useEffect(() => {
    const id = setTimeout(() => setOpen(true), 0);
    return () => clearTimeout(id);
  }, []);

  const requestClose = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setOpen(false);
    setTimeout(onClose, duration);
  }, [onClose, duration]);

  return { open, requestClose };
}
