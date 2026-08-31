# Design: Dead and Non-functional Code Cleanup

## Approach

Delete code with no consumers rather than replacing it with a new abstraction.
For the two visible admin stubs, remove both the entry point and modal: leaving
a disabled or generic placeholder would retain the same maintenance surface
without providing functionality.

The row overflow menus are treated the same way as the create controls:
Base Model **Edit/Remove** and Source Type **Edit/Remove** have no handlers.
Remove them rather than preserving clickable placeholders. Source Type's
mobile **View/Hide Info** action is functional and stays.

Deleting `DisasterEvents` also makes its direct `d3` dependency and
`public/assets/geo/world.geojson` fetch target unreachable. Remove both. The
different `src/assets/json/world.geojson` used by country selectors stays.

The four `hastegeo.core` package initializers currently append their own
directories to `sys.path`. All repository imports use qualified package paths;
an AST scan found no bare sibling imports. Keep the copyright/license header
and remove only the import-time side effect.

## Files

### Delete

- `ui/src/Components/ImageLayerInfoModal.jsx`
- `ui/src/Components/Home/DisasterEvents.jsx`
- `ui/src/Components/HelpDocs/HelpDocsPrevNext.jsx`
- `ui/src/Components/CreateEditBaseModelModal.jsx`
- `ui/src/Components/CreateEditSourceTypeModal.jsx`
- `ui/public/assets/geo/world.geojson`

### Modify

- `ui/src/util/api.js` — remove `resolveVarConcatChar`.
- `ui/src/Components/AdminBaseModels.jsx` — remove the non-functional create
  entry point.
- `ui/src/Components/AdminSourceTypes.jsx` — same.
- `ui/src/Components/ProjectManagement/BaseModelRow.jsx` — remove the
  non-functional overflow menu.
- `ui/src/Components/ProjectManagement/SourceTypeRow.jsx` — remove only the
  non-functional Edit/Remove items.
- `ui/package.json` and `ui/package-lock.json` — remove direct `d3`.
- `hastelib/src/hastegeo/core/{models,processors,data_layer,utils}/__init__.py`
  — remove `os`, `sys`, and `sys.path.append`.

## Validation

- Search the full repository for every deleted symbol.
- Run all discovered UI `*.test.js` files and a production UI build.
- Import representative modules from all four Python packages.
- Run the smallest existing Python test files covering package imports and
  metadata/config behavior.
