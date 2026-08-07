// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Loading Component
// This component displays a loading spinner with a "Loading" label. It is used to indicate
// that a background operation is in progress.

import { Spinner, Label } from "@fluentui/react-components";
import { AppContext } from "../../AppContext";
import { useContext } from "react";

const Loading = () => {
  const { appParams } = useContext(AppContext);
  const loadingText = appParams.loadingMessage || "Loading...";

  return (
    <>
      {appParams.isLoading && (
        <div
          className="app-loading-layer"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <div className="app-loading-mask" />
          <div className="app-loading-center">
            <div className="app-loading-card">
              <Label className="app-loading-message">{loadingText}</Label>
              <Spinner size="tiny" className="app-loading-spinner" />
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Loading;
