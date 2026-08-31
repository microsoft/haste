# Design: Dead and Non-functional Code Cleanup

## Approach

Delete code with no consumers rather than replacing it with a new abstraction.
For the two visible admin stubs, remove both the entry point and modal: leaving
a disabled or generic placeholder would retain the same maintenance surface
without providing functionality.

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

### Modify

- `ui/src/util/api.js` — remove `resolveVarConcatChar`.
- `ui/src/Components/AdminBaseModels.jsx` — remove the non-functional create
  entry point.
- `ui/src/Components/AdminSourceTypes.jsx` — same.
- `hastelib/src/hastegeo/core/{models,processors,data_layer,utils}/__init__.py`
  — remove `os`, `sys`, and `sys.path.append`.

## Validation

- Search the full repository for every deleted symbol.
- Run all discovered UI `*.test.js` files and a production UI build.
- Import representative modules from all four Python packages.
- Run the smallest existing Python test files covering package imports and
  metadata/config behavior.
