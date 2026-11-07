# Project Creation Form Help

## Status

In progress

## Summary

Add concise field-level guidance and a guided tour to the project creation drawer. The drawer can open from the global sidebar on any page, so its tour owns its initialization and cleanup rather than depending on a route component.

## Components

- `ui/src/AppContext.jsx`
- `ui/src/Components/CreateEditProjectModal.jsx`
- `ui/src/Components/GuidedTour.jsx`
- `ui/src/assets/css/style.css`

## Acceptance Criteria

- Fields without guidance display short, actionable hints.
- The creation drawer starts its own guided tour after its data loads.
- The tour works regardless of the page beneath the drawer.
- Users can restart the tour from the drawer header.
- Closing the drawer clears its tour state.
- Edit mode retains field hints but does not automatically launch the creation tour.