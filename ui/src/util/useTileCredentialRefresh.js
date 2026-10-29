// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "./api";
import {
  applyTileCredentialUpdate,
  createTileCredentialRefreshController,
} from "./tileCredentialRefresh";

function labelingToolDataEndpoint(projectId, imageLayerId) {
  return (
    "GetLayerLabelingToolData?projectId=" +
    encodeURIComponent(projectId) +
    "&imageLayerId=" +
    encodeURIComponent(imageLayerId)
  );
}

export function useTileCredentialRefresh({
  projectId,
  imageLayerId,
  dataRef,
  layerBindings,
  onApplied,
}) {
  const [tileRefreshFailed, setTileRefreshFailed] = useState(false);
  const controllerRef = useRef(null);
  const pendingInitialDataRef = useRef(null);
  const configRef = useRef({
    projectId,
    imageLayerId,
    dataRef,
    layerBindings,
    onApplied,
  });

  useEffect(() => {
    configRef.current = {
      projectId,
      imageLayerId,
      dataRef,
      layerBindings,
      onApplied,
    };
  }, [projectId, imageLayerId, dataRef, layerBindings, onApplied]);

  useEffect(() => {
    const controller = createTileCredentialRefreshController({
      fetchCredentials: () => {
        const config = configRef.current;
        return apiGet(
          labelingToolDataEndpoint(config.projectId, config.imageLayerId)
        );
      },
      applyCredentials: (nextData) => {
        const config = configRef.current;
        return applyTileCredentialUpdate({
          dataRef: config.dataRef,
          nextData,
          layerBindings: config.layerBindings,
          onApplied: config.onApplied,
        });
      },
      onError: () => setTileRefreshFailed(true),
      onSuccess: () => setTileRefreshFailed(false),
    });

    controllerRef.current = controller;
    if (pendingInitialDataRef.current) {
      controller.start(pendingInitialDataRef.current);
    }

    return () => {
      controller.dispose();
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    };
  }, [projectId, imageLayerId]);

  const startTileCredentialRefresh = useCallback((initialData) => {
    if (!initialData) return;
    pendingInitialDataRef.current = initialData;
    setTileRefreshFailed(false);
    controllerRef.current?.start(initialData);
  }, []);

  const retryTileCredentialRefresh = useCallback(
    () => controllerRef.current?.refresh() || Promise.resolve(false),
    []
  );

  return {
    tileRefreshFailed,
    startTileCredentialRefresh,
    retryTileCredentialRefresh,
  };
}
