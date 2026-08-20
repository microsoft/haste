# Keyboard Shortcuts

HASTE provides keyboard shortcuts for imagery comparison, labeling, and
building validation. Each supported view also includes a collapsible
**Keyboard shortcuts** section.

## Contents

- [General behavior](#general-behavior)
- [Results viewer](#results-viewer)
- [Interactive Labeler](#interactive-labeler)
- [Labeling Tool](#labeling-tool)
- [Building Validation](#building-validation)

## General Behavior

Letter shortcuts are not case-sensitive. HASTE ignores global shortcuts while
you type in a field or dropdown. Clicking a button, link, or switch does not
disable them — a control only keeps the keys it needs itself, such as
`Space` or `Enter` to activate a focused button, or the arrow keys inside a
dropdown.

The imagery comparison keys use the same direction across views:

- `A` shows pre-event imagery, or moves a swipe divider left.
- `S` centers a swipe divider when the view supports split comparison.
- `D` shows post-event imagery, or moves a swipe divider right.

In swipe views the divider is the control, and the pre-event map sits on the
left of it. Moving the divider left therefore uncovers more of the post-event
map, and moving it right uncovers more of the pre-event map.

## Results Viewer

| Shortcut | Action |
|---|---|
| `A` | Move the swipe divider fully left, uncovering the post-event map. |
| `S` | Center the swipe divider for an even comparison. |
| `D` | Move the swipe divider fully right, uncovering the pre-event map. |

## Interactive Labeler

| Shortcut | Action |
|---|---|
| `1` | Select **Intact**. |
| `2` | Select **Damaged**. |
| `3` | Select **Cloudy**. |
| `T` | Cycle through the available classes. |
| `P` | Toggle between labeled and predicted views when the model can train. |
| `Space` | Show or hide building footprints. |
| `Ctrl` + drag | Box-label buildings. |
| `A` | Move the enabled swipe divider left. |
| `S` | Center the enabled swipe divider. |
| `D` | Move the enabled swipe divider right. |

## Labeling Tool

| Shortcut | Action |
|---|---|
| `A` | Show pre-event imagery, or the basemap when pre-event imagery is unavailable. |
| `D` | Show post-event imagery. |

## Building Validation

| Shortcut | Action |
|---|---|
| `1` | Label the selected building **Damaged**. |
| `2` | Label the selected building **Not Damaged**. |
| `3` | Label the selected building **Unknown**. |
| `Left Arrow` | Select the previous building in the current filter. |
| `Right Arrow` | Select the next building in the current filter. |
| `A` | Show pre-event imagery, or the basemap when pre-event imagery is unavailable. |
| `D` | Show post-event imagery. Has no effect when the layer has no post-event imagery. |
