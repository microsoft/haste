# Dead and Non-functional Code Cleanup

**Status:** in-progress  
**Type:** modification  
**Issue:** [#181](https://github.com/microsoft/haste/issues/181)

## Summary

Remove verified unused UI modules, hide two admin creation controls whose
dialogs cannot submit anything, and remove four unnecessary package-level
`sys.path` mutations.

## Scope

- Delete `resolveVarConcatChar`, `ImageLayerInfoModal`, `DisasterEvents`, and
  `HelpDocsPrevNext`; repository-wide searches find no consumers.
- Remove the **New Base Model** and **New Source Type** buttons and their
  duplicate non-functional modal files.
- Remove the Base Model **Edit/Remove** and Source Type **Edit/Remove** menu
  items, which have no handlers. Preserve Source Type's working mobile
  **View/Hide Info** action.
- Remove `d3` and `public/assets/geo/world.geojson`, whose only consumer was
  `DisasterEvents`. Keep the separate country-boundary GeoJSON used by live
  project forms.
- Replace the `hastegeo.core.models`, `processors`, `data_layer`, and `utils`
  package initializers with side-effect-free package markers.

## Out of Scope

- Implementing base-model or source-type creation.
- Broader lint, formatting, or component refactors.
- Other findings from the repository simplification audit.

## Success Criteria

- Deleted symbols have no remaining references.
- Existing admin list, sort, and responsive Source Type info behavior are
  unchanged; placebo create/edit/remove actions are gone.
- `d3` is not a direct UI dependency and the orphaned public world map is gone.
- The four Python packages import without mutating `sys.path`.
- UI tests/build and targeted Python imports/tests pass.

## Agent Assignment Map

| Work | Implementing agent | Validating agent |
|---|---|---|
| UI removal | `ui` | `ui-validation` |
| Python package cleanup | `backend-dev` | `backend-validation` |
| Tracking | `orchestrator` | — |
