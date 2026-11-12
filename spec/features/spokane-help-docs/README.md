# Feature: Spokane Deep Dive in Help Docs

**Status:** implemented
**Date:** 2026-11-12
**Priority:** P2

## Contents

- [Summary](#summary)
- [Success Criteria](#success-criteria)
- [HASTE Components Affected](#haste-components-affected)
- [Document Index](#document-index)

## Summary

Embed Spokane Deep Dive in the Introduction of `/help-docs/overview`, directly
below the existing overview video. Reuse the six published recordings, previews,
and English captions without duplicating media.

## Success Criteria

- Introduction includes all six videos below the existing overview recording.
- The series has no separate page or sidebar/dropdown group.
- Each episode has a heading, duration, preview, captioned player, and video link.
- Direct section and episode URLs work without changing existing help content.
- Playback failures display an explicit message and an alternative link.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `ui/src/Components/HelpDocs*` | Introduction and embedded video walkthrough |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Rendering, navigation, and media handling | approved |
| [user-stories.md](user-stories.md) | Acceptance criteria and agent assignments | approved |
| [plan.md](plan.md) | Implementation and validation status | implemented |
