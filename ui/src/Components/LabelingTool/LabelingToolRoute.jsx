import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PropTypes from "prop-types";

import { apiGet } from "../../util/api";
import { loadAzureMaps } from "../../util/azureMapsLoader";
import WorkspaceLoader from "../WorkspaceLoader";
import { loadLabelingRoute } from "./loadLabelingRoute";

const LOAD_STEPS = [
  "Loading workspace data and map tools",
  "Preparing imagery and labels",
  "Rendering map and drawing tools",
];

const LabelingToolRoute = ({ setModalComponent }) => {
  const { projectId, imageLayerId } = useParams();
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState(0);
  const [loadedRoute, setLoadedRoute] = useState(null);
  const [loadState, setLoadState] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const loadKey = `${projectId}:${imageLayerId}:${attempt}`;

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const requestKey = loadKey;

    loadLabelingRoute({
      importRoute: () => import("./LabelingTool"),
      loadMaps: () =>
        loadAzureMaps(document, { drawing: true, swipe: false }),
      get: apiGet,
      projectId,
      imageLayerId,
      signal: controller.signal,
    })
      .then((result) => {
        if (!active) return;
        setLoadState({
          key: requestKey,
          value: { step: 1, loaded: null, total: null },
        });
        setLoadedRoute({
          ...result,
          key: requestKey,
          signal: controller.signal,
        });
      })
      .catch((error) => {
        if (!active || error.name === "AbortError") return;
        controller.abort();
        setLoadError({
          key: requestKey,
          value: "The labeling workspace could not be loaded.",
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [imageLayerId, loadKey, projectId]);

  const currentRoute = loadedRoute?.key === loadKey ? loadedRoute : null;
  const Component = currentRoute?.Component;
  const currentError = loadError?.key === loadKey ? loadError.value : "";
  const currentLoadState = currentError
    ? null
    : loadState?.key === loadKey
      ? loadState.value
      : { step: 0, loaded: null, total: null };
  return (
    <div className="labeling-workspace-route">
      <WorkspaceLoader
        eyebrow="Standard labeling tool"
        title="Preparing your workspace"
        steps={LOAD_STEPS}
        loadState={currentLoadState}
        error={currentError}
        errorTitle="Could not load the labeling workspace"
        onGoBack={() => navigate(-1)}
        onRetry={() => setAttempt((value) => value + 1)}
      />
      {Component && (
        <Component
          key={attempt}
          setModalComponent={setModalComponent}
          workspace={currentRoute.workspace}
          signal={currentRoute.signal}
          onLoadStep={(step) =>
            setLoadState({
              key: loadKey,
              value: { step, loaded: null, total: null },
            })
          }
          onReady={() => setLoadState({ key: loadKey, value: null })}
          onError={(message) => {
            setLoadError({ key: loadKey, value: message });
          }}
        />
      )}
    </div>
  );
};

LabelingToolRoute.propTypes = {
  setModalComponent: PropTypes.func.isRequired,
};

export default LabelingToolRoute;
