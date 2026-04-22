// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Loading Component
// This component displays a loading spinner with a "Loading" label. It is used to indicate
// that a background operation is in progress.

import { Spinner, SpinnerSize } from "@fluentui/react/lib/Spinner";
import { Label } from "@fluentui/react/lib/Label";
import { AppContext } from "../../AppContext";
import { useContext } from "react";

const Loading = () => {
  const { appParams } = useContext(AppContext);

  return (
    <>
      {appParams.isLoading && (
        <>
          <div style={{ zIndex: "100000000000000000000" }}>
            <div
              className=""
              style={{
                position: "fixed",
                top: "0px",
                left: "0px",
                width: "100%",
                height: "100%",
                backgroundColor: "#000000",
                opacity: ".3",
                pointerEvents: "none",
              }}
            ></div>
          </div>

          <div style={{ zIndex: "100000000000000000000" }}>
            <div
              className="d-flex flex-row flex-grow-1 align-items-center justify-content-center"
              style={{
                position: "fixed",
                top: "0px",
                left: "0px",
                width: "100%",
                height: "100%",
              }}
            >
              {/* Loading Spinner */}
              <div
                className="d-flex p-3"
                style={{
                  backgroundColor: "#FFFFFF",
                  borderRadius: "5px",
                  boxShadow: "5px 5px 15px 5px #000000, .5",
                }}
              >
                <Label className="me-2 custom-loading-spinner-color">{appParams.loadingMessage}</Label>
                <Spinner size={SpinnerSize.large} />
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
};

export default Loading;
