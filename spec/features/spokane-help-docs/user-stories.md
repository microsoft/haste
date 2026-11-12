# User Stories: Spokane Deep Dive in Help Docs

## US-001: Discover the walkthrough

As a disaster analyst, I want Spokane videos within Introduction so I can
continue from the overview into a detailed demonstration on the same page.

- All six episodes appear directly below the existing overview video.
- Desktop and mobile navigation retain Overview > Introduction without a
  separate Spokane group.
- Direct episode URLs and browser back/forward preserve the selected content.

## US-002: Watch accessible episodes

As a disaster analyst, I want previews and English captions so I can choose
and follow an episode at my own pace.

- Six episodes retain their published order, titles, and durations.
- Every player has a preview, English caption track, and native controls.
- Players do not preload recordings or autoplay.
- Every episode offers a new-tab video link; playback errors are announced.

## Agent Assignment Map

| Story | Implementing Agent | Validating Agent |
|---|---|---|
| US-001 | `ui` | `ui-validation` |
| US-002 | `ui` | `ui-validation` |
