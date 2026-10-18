# Project Creation Form Help Design

## Problem

The project creation form validates required data but gives little guidance before submission. Because the form opens from the global sidebar, page-specific tour initialization cannot reliably explain it.

## Design

Use Fluent UI `Field` hints for concise, accessible guidance next to name, description, event date, affected countries, and event types. Keep the existing primary-class explanation rather than duplicating it.

Define a dedicated `createProjectGuide` tour with its own dismissal key. The drawer starts the tour after loading its state, exposes a Help button in its header, and clears the tour when it unmounts. Each step targets a compact control so the spotlight and coach card remain usable in small remote-desktop viewports.

Render the tour overlay in the application viewport rather than inside the drawer portal. Target rectangles use viewport coordinates, and keeping the overlay in that same coordinate space prevents the drawer transform from offsetting the spotlight. A high overlay stacking level keeps the global tour above the drawer regardless of the route beneath it.

The tour runs only in create mode because event types and primary classes are immutable in edit mode. Field hints remain useful in both modes.

## Security And Accessibility

Tour content is static application text and does not include user-provided HTML. Hints use Fluent UI field semantics, and comboboxes receive descriptive accessible labels.