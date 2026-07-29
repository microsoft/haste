// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useEffect } from "react";
import { Dropdown, Option } from "@fluentui/react-components";

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
              className="me-2"
              selectedOptions={[
                String(componentState[currentEventImageryUrlControl] ?? ""),
              ]}
              value={
                componentState.imageryOriginOptions.find(
                  (o) => o.key === componentState[currentEventImageryUrlControl]
                )?.text || ""
              }
              onOptionSelect={(e, data) =>
                onFormChange(
                  data.optionValue,
                  currentEventImageryUrlControl,
                  setComponentState,
                  componentState
                )
              }
              disabled={imageLayerId ? true : false}
            >
              {componentState.imageryOriginOptions.map((o) => (
                <Option key={o.key} value={String(o.key)}>
                  {o.text}
                </Option>
              ))}
            </Dropdown>
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
