---
applyTo: "**/*.jsx,**/*.js,ui/**"
---

# React / UI Instructions

- React functional components with hooks — no class components.
- Use FluentUI (`@fluentui/react`) for all UI elements — no alternative frameworks.
- Use Azure Maps for geospatial visualization — no Leaflet or Mapbox.
- Use MSAL (`@azure/msal-react`) for authentication — do not bypass in production paths.
- Use `@turf/turf` for client-side geospatial calculations.
- Use Chart.js via `react-chartjs-2` for statistics dashboards.
- Keep helper files (`*Helper.js`) alongside their components.
- Use `AppContext.jsx` for global state, `useState` for component-local state.
- Run `cd ui && npm run lint` before committing changes.
- Run `cd ui && npm run build` to verify production builds succeed.
