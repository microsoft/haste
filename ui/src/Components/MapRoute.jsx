import { Button, Spinner } from "@fluentui/react-components";
import { useEffect, useState } from "react";

import { loadMapRoute } from "../util/azureMapsLoader";


export const RouteLoading = () => (
  <div className="route-loading" role="status" aria-live="polite">
    <Spinner size="small" label="Loading page" />
  </div>
);

// eslint-disable-next-line react-refresh/only-export-components
export function createMapRoute(importRoute) {
  const MapRoute = (props) => {
    const [attempt, setAttempt] = useState(0);
    const [routeComponent, setRouteComponent] = useState(null);
    const [loadError, setLoadError] = useState(false);

    useEffect(() => {
      let active = true;
      loadMapRoute(importRoute)()
        .then((route) => {
          if (active) setRouteComponent(() => route.default);
        })
        .catch(() => {
          if (active) setLoadError(true);
        });
      return () => {
        active = false;
      };
    }, [attempt]);

    if (loadError) {
      return (
        <div className="route-loading" role="alert">
          <div className="d-flex flex-column align-items-center gap-3">
            <span>Map assets could not be loaded.</span>
            <Button
              appearance="primary"
              onClick={() => {
                setLoadError(false);
                setRouteComponent(null);
                setAttempt((value) => value + 1);
              }}
            >
              Retry
            </Button>
          </div>
        </div>
      );
    }
    if (!routeComponent) return <RouteLoading />;

    const Component = routeComponent;
    return <Component {...props} />;
  };
  return MapRoute;
}