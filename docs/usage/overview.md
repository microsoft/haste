<!-- SOURCE: Landing page for the workflow-first User Guide. The end-to-end video
     comes from the in-app Help Docs overview
     (ui/src/Components/HelpDocs/HelpDocsOverview.jsx). -->

# Overview

**HASTE** (High-speed Assessment and Satellite Tracking for Emergencies) is an AI-powered
tool from the **Microsoft AI for Good Lab** for quickly assessing building damage after a
disaster. You add satellite imagery, label a small amount of it, and HASTE predicts damage
across the whole area.

<video controls width="100%" src="../_static/usage/overview/overview-end-to-end-example.mp4">
Your browser does not support the video tag.
</video>

## Choose your path

HASTE offers two workflows that both turn imagery into a damage assessment — pick based on
what you need and how fast you need it.

| | {doc}`Rapid Building Assessment <rapid-building-assessment>` | {doc}`Damage Mapping <damage-mapping>` |
|---|---|---|
| **How it works** | Embed buildings → label a few → an in-browser model predicts the rest → validate → report | Draw labels → train a segmentation model → predict across the whole image |
| **Output** | Per-building damaged/intact, with accuracy metrics and a damaged-building estimate | A continuous damage map + downloadable geopackage |
| **Speed** | Minutes — no training job | Slower — GPU model training and inference |
| **Needs** | Building footprints for the area | Just imagery |

```{admonition} Not sure? Start here.
:class: tip

If you have building footprints and want an answer fast, use
{doc}`Rapid Building Assessment <rapid-building-assessment>` — it's the quickest route from
imagery to a damage assessment. Choose {doc}`Damage Mapping <damage-mapping>` when you need a
continuous, pixel-level damage raster.
```

Both workflows start the same way — create a project and add an image layer — then diverge.
Those shared building blocks have their own pages: {doc}`Projects <projects>`,
{doc}`Image layers <image-layers>`, and the {doc}`Model catalog <model-catalog>`.
See {doc}`Keyboard shortcuts <keyboard-shortcuts>` for the controls available
across map and labeling views.
