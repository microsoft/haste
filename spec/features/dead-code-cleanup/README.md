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
- Replace the `hastegeo.core.models`, `processors`, `data_layer`, and `utils`
  package initializers with side-effect-free package markers.

## Out of Scope

- Implementing base-model or source-type creation.
- Broader lint, formatting, or component refactors.
- Other findings from the repository simplification audit.

## Success Criteria

- Deleted symbols have no remaining references.
- Existing admin list and remove actions are unchanged.
- The four Python packages import without mutating `sys.path`.
- UI tests/build and targeted Python imports/tests pass.

## Agent Assignment Map

| Work | Implementing agent | Validating agent |
|---|---|---|
| UI removal | `ui` | `ui-validation` |
| Python package cleanup | `backend-dev` | `backend-validation` |
| Tracking | `orchestrator` | — |
