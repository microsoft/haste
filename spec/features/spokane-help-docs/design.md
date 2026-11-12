# Technical Design: Spokane Deep Dive in Help Docs

## Contents

- [Overview](#overview)
- [Navigation](#navigation)
- [Media](#media)
- [Validation](#validation)

## Overview

Render the video series inside HelpDocsOverview, immediately after the existing
overview video and before the workflow cards. Use an H2 for the series and H3
headings for its episodes. No backend, authentication, or deployment changes
are required.

## Navigation

Keep Overview > Introduction as the navigation entry. Do not add a separate
Spokane group or page. The series is available at
`/help-docs/overview#spokane-deep-dive`, with episode anchors
`#spokane-<episode-slug>` to avoid colliding with the Introduction anchor.
Keep browser history and direct URLs synchronized with React Router.

## Media

Reuse `https://microsoft.github.io/haste/_static/usage/spokane-deep-dive/`
for MP4, JPEG, and WebVTT assets. Preserve the episode order and durations from
the [published guide](../../../docs/usage/spokane-deep-dive.md).
Players use native controls, `preload="none"`, `playsInline`, accessible labels,
and `crossOrigin="anonymous"` so hosted English captions can load.

Keep an always-visible new-tab video link below each player. Display a
`role="alert"` message if playback fails. Do not autoplay or copy large assets
into the UI bundle.

The seven existing Overview, Projects, and Image Layers videos also use local
JPEG posters, imported alongside their MP4s with the same basename. Extract
the title frame from each recording at 1 second using FFmpeg
`-vf "thumbnail=30,scale=1280:-2" -frames:v 1 -q:v 3`. Keep `preload="none"`
so displaying a preview does not download the recording.

## Validation

Use Node's existing test runner to check episode metadata and local assets. Run a
production build and targeted ESLint. Use Playwright to verify desktop/mobile
navigation, inline placement, direct episode URLs, captions, and playback errors.
