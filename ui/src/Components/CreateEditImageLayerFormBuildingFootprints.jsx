// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState, useEffect } from "react";
import propTypes from "prop-types";
import {
  Text,
  Toggle,
  Dropdown,
  TextField,
  PrimaryButton,
} from "@fluentui/react";

import CreateEditImageLayerURL from "./CreateEditImageLayerURL";
import CreateEditImageLayerFileUploader from "./CreateEditImageLayerFileUploader";
import {
  addUrlToFootprintArray,
  addFootprintFileToArray,
  onFormChange,
} from "./CreateEditImageLayerHelper";

const FIELD = "userBuildingFootprintsUrls";
const CONTROL = "currentUserBuildingFootprintsControl";
const CONTROL_ERROR = "currentUserBuildingFootprintsControlError";

const CreateEditImageLayerFormBuildingFootprints = ({
  componentState,
  setComponentState,
  imageLayerId,
}) => {
  CreateEditImageLayerFormBuildingFootprints.propTypes = {
    componentState: propTypes.object.isRequired,
    setComponentState: propTypes.func.isRequired,
    imageLayerId: propTypes.string,
  };

  // The field is create-only — once a layer exists, the workflow has
  // already run, so we just display whatever was provided originally.
  const editingExisting = !!imageLayerId;

  const enabled = !!componentState.userBuildingFootprintsEnabled;
  const entries = componentState[FIELD] || [];
  const control = componentState[CONTROL];
  const controlError = componentState[CONTROL_ERROR];

  const [urlInput, setUrlInput] = useState("");
  const [pickedFile, setPickedFile] = useState(null);

  // Clear stale state when the toggle is switched off so submitting
  // doesn't accidentally send a URL the user no longer wants. Uses
  // the functional setState form so the update always applies to the
  // latest state — spreading `componentState` captured in the closure
  // would overwrite newer form edits made between renders.
  useEffect(() => {
    if (!enabled) {
      setComponentState((prev) => {
        const existingEntries = prev[FIELD] || [];
        const existingError = prev[CONTROL_ERROR];
        if (existingEntries.length === 0 && !existingError) {
          return prev;
        }
        return { ...prev, [FIELD]: [], [CONTROL_ERROR]: "" };
      });
      setUrlInput("");
      setPickedFile(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  function handleToggle(_e, checked) {
    onFormChange(!!checked, "userBuildingFootprintsEnabled", setComponentState, componentState);
  }

  function handleUrlAdd() {
    if (
      addUrlToFootprintArray(
        setComponentState,
        componentState,
        urlInput,
        FIELD,
        CONTROL_ERROR
      )
    ) {
      setUrlInput("");
    }
  }

  function handleFileAdd() {
    if (
      addFootprintFileToArray(
        pickedFile ? [pickedFile] : [],
        componentState,
        setComponentState,
        FIELD,
        CONTROL_ERROR
      )
    ) {
      setPickedFile(null);
      const el = document.getElementById("userBuildingFootprintsFileInput");
      if (el) el.value = null;
    }
  }

  return (
    <div className="row mb-2 p-2">
      <div className="col-12 p-4 flex-column d-flex box-highlight">
        <div className="col-12 mb-3">
          <h6 className="m-0 pb-2">Custom Building Footprints</h6>
          <Text variant="medium">
            Optional. By default, building footprints are downloaded from
            Overture Maps using the area-of-interest derived from the
            post-event imagery. Enable this panel to instead supply your
            own building-footprints GeoPackage (.gpkg). The file will be
            reprojected to EPSG:4326 and clipped to the AOI before use.
          </Text>
        </div>

        <div className="col-12 mb-3">
          <Toggle
            label="Use custom building footprints (skip Overture download)"
            checked={enabled}
            onChange={handleToggle}
            disabled={editingExisting}
            inlineLabel
          />
        </div>

        {enabled && (
          <React.Fragment>
            <div className="row mb-2">
              <div className="col-12 d-flex">
                <Dropdown
                  options={componentState.imageryOriginOptions}
                  selectedKey={control}
                  defaultSelectedKey={control}
                  onChange={(_e, item) =>
                    onFormChange(item.key, CONTROL, setComponentState, componentState)
                  }
                  className="me-2"
                  disabled={editingExisting}
                />
                {control === "url" || control === "" ? (
                  <React.Fragment>
                    <TextField
                      className="flex-grow-1 me-2"
                      placeholder="Write or paste a .gpkg URL"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      errorMessage={controlError}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleUrlAdd();
                      }}
                      disabled={editingExisting || entries.length > 0}
                    />
                    <PrimaryButton
                      onClick={handleUrlAdd}
                      disabled={!urlInput || editingExisting || entries.length > 0}
                    >
                      Add
                    </PrimaryButton>
                  </React.Fragment>
                ) : (
                  <React.Fragment>
                    <input
                      type="file"
                      multiple={false}
                      accept=".gpkg"
                      className="d-none"
                      id="userBuildingFootprintsFileInput"
                      aria-label="Building footprints file input"
                      onChange={(e) => {
                        if (e.target.files && e.target.files.length > 0) {
                          setPickedFile(e.target.files[0]);
                        } else {
                          setPickedFile(null);
                        }
                      }}
                    />
                    <TextField
                      className="flex-grow-1 me-2 cursor-pointer-on-hover"
                      placeholder="Click here to select a .gpkg file"
                      value={pickedFile ? pickedFile.name : ""}
                      readOnly
                      errorMessage={controlError}
                      onClick={() => {
                        const el = document.getElementById("userBuildingFootprintsFileInput");
                        if (el) el.click();
                      }}
                      disabled={editingExisting || entries.length > 0}
                    />
                    <PrimaryButton
                      onClick={handleFileAdd}
                      disabled={!pickedFile || editingExisting || entries.length > 0}
                    >
                      Upload
                    </PrimaryButton>
                  </React.Fragment>
                )}
              </div>
            </div>

            {entries.length > 0 && (
              <div className="row mb-2 ps-3 pe-3 d-flex flex-column">
                {entries.map((entry, index) => (
                  <div
                    key={"footprint" + index}
                    className="col-12 d-flex align-items-center mb-1 p-0 pb-3 pt-2"
                    style={{ borderBottom: "1px solid #eaeaea" }}
                  >
                    {entry.type === "url" ? (
                      <CreateEditImageLayerURL
                        setComponentState={setComponentState}
                        componentState={componentState}
                        url={entry}
                        field={FIELD}
                        imageLayerId={imageLayerId}
                      />
                    ) : (
                      <CreateEditImageLayerFileUploader
                        setComponentState={setComponentState}
                        componentState={componentState}
                        file={entry}
                        field={FIELD}
                        dataFormat="gpkg"
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </React.Fragment>
        )}
      </div>
    </div>
  );
};

export default CreateEditImageLayerFormBuildingFootprints;
