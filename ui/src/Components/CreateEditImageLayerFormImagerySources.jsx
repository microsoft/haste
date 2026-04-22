// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useEffect } from "react";
import { Dropdown } from "@fluentui/react";

import CreateEditImageLayerFormFile from "./CreateEditImageLayerFormFile";
import CreateEditImageLayerFileUploader from "./CreateEditImageLayerFileUploader";
import CreateEditImageLayerFormURL from "./CreateEditImageLayerFormURL";
import CreateEditImageLayerURL from "./CreateEditImageLayerURL";

import propTypes from "prop-types";

const CreateEditImageLayerFormImagerySources = ({
  onFormChange,
  componentState,
  setComponentState,
  field,
  currentEventImageryUrlControl,
  imageLayerId
}) => {
  CreateEditImageLayerFormImagerySources.propTypes = {
    onFormChange: propTypes.func.isRequired,
    componentState: propTypes.object.isRequired,
    setComponentState: propTypes.func.isRequired,
    field: propTypes.string.isRequired,
    currentEventImageryUrlControl: propTypes.string.isRequired,
    imageLayerId: propTypes.string,
  };


  useEffect(() => {

  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentState[field]]);

  useEffect(() => {
    
    onFormChange("", currentEventImageryUrlControl + "Error", setComponentState, componentState);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentState[currentEventImageryUrlControl]]);

  return (
    <React.Fragment>
      <div className="row mb-2">
        <div className="col-12 d-flex flex-column mb-3">
          <div className="col-12 d-flex">
            <Dropdown
              options={componentState.imageryOriginOptions}
              onChange={(e, item) =>
                onFormChange(
                  item.key,
                  currentEventImageryUrlControl,
                  setComponentState,
                  componentState
                )
              }
              selectedKey={componentState[currentEventImageryUrlControl]}
              className="me-2"
              defaultSelectedKey={
                componentState[currentEventImageryUrlControl]
              }
              disabled={imageLayerId ? true : false}
            />
            {componentState[currentEventImageryUrlControl] === "url" ||
            componentState[currentEventImageryUrlControl] === "" ? (
              <CreateEditImageLayerFormURL
                setComponentState={setComponentState}
                componentState={componentState}
                field={field}
                currentEventImageryUrlControl={currentEventImageryUrlControl}
                imageLayerId={imageLayerId}
              />
            ) : (
              <CreateEditImageLayerFormFile
                setComponentState={setComponentState}
                componentState={componentState}
                field={field}
                currentEventImageryUrlControl={currentEventImageryUrlControl}
                imageLayerId={imageLayerId}
              />
            )}
          </div>
        </div>
      </div>

      {componentState[field].length > 0 && (
        <div className="row mb-3 ps-3 pe-3 d-flex flex-column">
          {componentState[field].map((url, index) => (
            <div
              key={"url" + index}
              className="col-12 d-flex align-items-center mb-1 p-0 pb-3 pt-2"
              style={{ borderBottom: "1px solid #eaeaea" }}
            >
              {url.type === "url" ? (
                <CreateEditImageLayerURL
                  setComponentState={setComponentState}
                  componentState={componentState}
                  url={url}
                  field={field}
                  imageLayerId={imageLayerId}
                />
              ) : (
                <CreateEditImageLayerFileUploader
                  setComponentState={setComponentState}
                  componentState={componentState}
                  file={url}
                  field={field}
                  onFormChange={onFormChange}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </React.Fragment>
  );
};

export default CreateEditImageLayerFormImagerySources;
