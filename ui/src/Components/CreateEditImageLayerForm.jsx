// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext, useEffect } from "react";
import {
  TextField,
  PrimaryButton,
  Text,
  DatePicker,
  Dropdown,
} from "@fluentui/react";

import { useParams } from "react-router-dom";
import SectionHeader from "./Section/SectionHeader";
import CreateEditImageLayerFormImagerySources from "./CreateEditImageLayerFormImagerySources";
import CreateEditImageLayerFormBuildingFootprints from "./CreateEditImageLayerFormBuildingFootprints";

import {
  createComponentDefaultState,
  onFormChange,
  getUrlList,
} from "./CreateEditImageLayerHelper";

import { apiPut } from "../util/api";
import {
  validateEmptyOrInvalid,
  validateEmpty,
  validateAtLeastSomeNumber,
  validateIsUploading,
} from "../util/validation";
import { AppContext } from "../AppContext";
import { useNavigate } from "react-router-dom";

const CreateEditImageLayerModal = () => {
  const { setDialog, appParams, setIsLoading, setAppHeaderRightButtons } =
    useContext(AppContext);
  const [componentState, setComponentState] = useState(null);
  const navigate = useNavigate();

  const projectId = useParams().projectId;
  const imageLayerId = useParams().imageLayerId;
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    async function initComponent() {
      setIsLoading(true);
      setComponentState(
        await createComponentDefaultState(imageLayerId, projectId)
      );
      setIsLoading(false);
    }

    initComponent();

    return () => {
      setAppHeaderRightButtons([]);
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (componentState) {
      setIsUploading(
        validateIsUploading(
          componentState.preEventImageryUrls,
          componentState.postEventImageryUrls,
          componentState.userBuildingFootprintsUrls || []
        )
      );
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentState]);

  /* SUBMIT FUNCTION */
  async function submit() {
    const {
      name,
      description,
      preEventImageryUrls,
      postEventImageryUrls,
      format,
      sourceTypePreEvent,
      sourceTypePostEvent,
      normalizationFactor,
      imageryCaptureDatePreEvent,
      imageryCaptureDatePostEvent,
    } = componentState;

    const nameError = validateEmptyOrInvalid(true, "Name", name);

    const currentPostEventImageryUrlControlError = validateAtLeastSomeNumber(
      "Imagery URLs",
      postEventImageryUrls,
      1
    );

    const formatError = validateEmpty("Format", format);
    const sourceTypePreEventError = validateEmpty(
      "Source Type",
      sourceTypePreEvent
    );
    const sourceTypePostEventError = validateEmpty(
      "Source Type",
      sourceTypePostEvent
    );
    const normalizationFactorError = validateEmpty(
      "Normalization Factor",
      normalizationFactor
    );
    const imageryCaptureDatePostEventError = validateEmpty(
      "Imagery Capture Date",
      imageryCaptureDatePostEvent
    );

    // When the user enabled the custom-footprints panel, they must
    // actually supply a URL/file. Otherwise the workflow would silently
    // fall back to Overture even though the user explicitly chose not to,
    // which is a correctness failure.
    let userBuildingFootprintsControlError = "";
    if (componentState.userBuildingFootprintsEnabled && !imageLayerId) {
      const entries = componentState.userBuildingFootprintsUrls || [];
      const firstReady =
        entries.length > 0 &&
        entries[0].type === "url" &&
        !!entries[0].value;
      if (!firstReady) {
        userBuildingFootprintsControlError =
          "Add a building-footprints URL or upload a .gpkg file, or disable the custom footprints panel.";
      }
    }

    if (
      nameError ||
      currentPostEventImageryUrlControlError ||
      formatError ||
      sourceTypePreEventError ||
      sourceTypePostEventError ||
      normalizationFactorError ||
      imageryCaptureDatePostEventError ||
      userBuildingFootprintsControlError
    ) {
      setComponentState({
        ...componentState,
        nameError: nameError,
        currentPostEventImageryUrlControlError:
          currentPostEventImageryUrlControlError,
        formatError: formatError,
        sourceTypePreEventError: sourceTypePreEventError,
        sourceTypePostEventError: sourceTypePostEventError,
        normalizationFactorError: normalizationFactorError,
        imageryCaptureDatePostEventError: imageryCaptureDatePostEventError,
        currentUserBuildingFootprintsControlError:
          userBuildingFootprintsControlError,
      });
      return;
    }

    const buttons = [
      {
        type: "primary",
        key: "close",
        text: "Close",
        onClick: () => {
          setDialog("", "", []);
          navigate("/project/" + componentState.projectId);
        },
      },
    ];

    setIsLoading(true, "Processing Image Layer...");

    try {
      if (imageLayerId) {
        var tempComponentState = {
          ...componentState,
          preEventImageryUrls: getUrlList(preEventImageryUrls),
          postEventImageryUrls: getUrlList(postEventImageryUrls),
        };

        await apiPut("PutLayer/", tempComponentState);
        setDialog("Success", "Imagelayer successfully updated.", buttons);
      } else {
        // Resolve the user-supplied building-footprint URL (if enabled
        // and any entry has been added). File entries are flipped to
        // url-type once the chunked upload completes
        // (validateIsUploading above already blocks submit otherwise).
        const userFootprintEntries = componentState.userBuildingFootprintsUrls || [];
        let userBuildingFootprintsUrl = null;
        if (componentState.userBuildingFootprintsEnabled && userFootprintEntries.length > 0) {
          const first = userFootprintEntries[0];
          if (first && first.type === "url" && first.value) {
            userBuildingFootprintsUrl = first.value;
          }
        }

        const apiBody = {
          projectId: componentState.projectId,
          name: name,
          description: description,
          preEventImageryUrls: getUrlList(preEventImageryUrls),
          postEventImageryUrls: getUrlList(postEventImageryUrls),
          format: format,
          sourceTypePreEvent: sourceTypePreEvent,
          sourceTypePostEvent: sourceTypePostEvent,
          normalizationFactor: normalizationFactor,
          imageryCaptureDatePreEvent: imageryCaptureDatePreEvent,
          imageryCaptureDatePostEvent: imageryCaptureDatePostEvent,
          userBuildingFootprintsUrl: userBuildingFootprintsUrl,
          userId: appParams.userId,
        };

        await apiPut("PutLayer", apiBody);
        setDialog("Success", "Imagelayer successfully created.", buttons);
      }
    } catch (error) {
      console.error(error);
      setDialog("Error", "An error occurred while saving the image layer.", []);
    }
    setIsLoading(false);
  }

  if (!componentState) {
    return null;
  }

  return (
    <div className="d-flex flex-column col">
      <SectionHeader properties={componentState.sectionHeaderProperties} />
      <div className="container d-flex justify-content-center mt-3 mb-3 mt-lg-5 mb-lg-5">
        <div className="col-12 col-md-9 col-lg-8 col-xl-6">
          <div className="row mb-2">
            <div className="col-12">
              <TextField
                required
                id="createEditImageLayerName"
                maxLength={250}
                label="Name"
                onChange={(e, newValue) =>
                  onFormChange(
                    newValue,
                    "name",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.nameError}
                value={componentState.name}
              />
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12">
              <TextField
                id="createEditImageLayerDescription"
                multiline
                rows={5}
                label="Description"
                description={
                  componentState.description.length + "/2000 " + "characters"
                }
                maxLength={2000}
                onChange={(e, newValue) =>
                  onFormChange(
                    newValue,
                    "description",
                    setComponentState,
                    componentState
                  )
                }
                value={componentState.description}
              />
            </div>
          </div>

          <div className="row mb-2 p-2">
            <div className="col-12 p-4  flex-column d-flex box-highlight">
              <div className="col-12">
                <h6 className="m-0 pb-2">Imagery Details</h6>
                <Text variant="medium">
                  Add imagery files by providing publicly accessible URLs or
                  uploading files from a local directory that show the Area of
                  Interest (AOI). If multiple files are provided in a section,
                  they will be merged into a single GeoTIFF image; therefore,
                  all files in a given section must correspond to the same AOI.
                  You can combine files from both a URL and a local directory if
                  needed. All files must be valid GeoTIFF (.tif) files.
                </Text>
              </div>
            </div>
          </div>

          <div className="row mb-2 p-2">
            <div className="col-12 p-4 pb-0 flex-column d-flex box-highlight">
              <div className="col-12 mb-4">
                <h6 className="m-0 pb-3">
                  Post-Event Imagery
                  <span className="required-form-element"> *</span>
                </h6>
                <Text variant="medium" className="">
                  This section is <span className="fw-semibold">required</span>.
                  Here you must add imagery files that represent an AOI captured
                  after the date of the natural catastrophe. Select the
                  &quot;Source Type&quot; that matches your images for the best
                  labeling experience.
                </Text>
              </div>
              <CreateEditImageLayerFormImagerySources
                onFormChange={onFormChange}
                setComponentState={setComponentState}
                componentState={componentState}
                field="postEventImageryUrls"
                currentEventImageryUrlControl="currentPostEventImageryUrlControl"
                imageLayerId={imageLayerId}
              />
            </div>

            <div className="col-12 p-4 pt-0 d-flex flex-column flex-md-row  box-highlight">
              <DatePicker
                label="Imagery capture date"
                id="createEditImageLayerImageryCapturePostEventDate"
                placeholder="Select a date..."
                ariaLabel="Select a date"
                className="flex-grow-1 me-0 me-md-2"
                onSelectDate={(e) =>
                  onFormChange(
                    e,
                    "imageryCaptureDatePostEvent",
                    setComponentState,
                    componentState
                  )
                }
                required
                isRequired={componentState.imageryCaptureDatePostEventError}
                value={
                  componentState.imageryCaptureDatePostEvent !== ""
                    ? new Date(componentState.imageryCaptureDatePostEvent)
                    : ""
                }
                disabled={imageLayerId ? true : false}
              />
              <Dropdown
                id="createEditImageLayerPostEventSourceType"
                placeholder="Select a Source Type"
                label="Source type"
                options={componentState.sourceTypeList.filter(
                  (option) => option.showInDropdown
                )}
                value={componentState.sourceTypePostEvent}
                onChange={(e, item) =>
                  onFormChange(
                    item.key,
                    "sourceTypePostEvent",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.sourceTypePostEventError}
                selectedKey={componentState.sourceTypePostEvent}
                className="flex-grow-1 me-0 me-md-2"
                disabled={imageLayerId ? true : false}
              />
              <Dropdown
                placeholder="Select a Format"
                label="Format"
                options={[{ key: "tif", text: "Tif" }]}
                value={componentState.format}
                onChange={(e, item) =>
                  onFormChange(
                    item.key,
                    "format",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.formatError}
                selectedKey={componentState.format}
                className="flex-grow-1 mb-2"
                disabled={imageLayerId ? true : false}
              />
            </div>
          </div>

          <div className="row mb-2 p-2">
            <div className="col-12 p-4 pb-0 flex-column d-flex box-highlight">
              <div className="col-12 mb-4">
                <h6 className="m-0 pb-3">Pre-Event Imagery</h6>
                <Text variant="medium">
                  This section is optional. Here you can add imagery files that
                  represent an AOI captured prior to the date of the natural
                  catastrophe. Select the &quot;Source Type&quot; that matches
                  your images for the best labeling experience.
                </Text>
              </div>
              <CreateEditImageLayerFormImagerySources
                onFormChange={onFormChange}
                setComponentState={setComponentState}
                componentState={componentState}
                field="preEventImageryUrls"
                currentEventImageryUrlControl="currentPreEventImageryUrlControl"
                imageLayerId={imageLayerId}
              />
            </div>

            <div className="col-12 p-4 pt-0 d-flex flex-column flex-md-row box-highlight">
              <DatePicker
                label="Imagery capture date  "
                id="createEditImageLayerImageryCapturePretEventDate"
                placeholder="Select a date..."
                ariaLabel="Select a date"
                className="flex-grow-1 me-0 me-md-2"
                onSelectDate={(e) =>
                  onFormChange(
                    e,
                    "imageryCaptureDatePreEvent",
                    setComponentState,
                    componentState
                  )
                }
                value={
                  componentState.imageryCaptureDatePreEvent !== ""
                    ? new Date(componentState.imageryCaptureDatePreEvent)
                    : ""
                }
                disabled={imageLayerId ? true : false}
              />
              <Dropdown
                id="createEditImageLayerPreEventSourceType"
                placeholder="Select a Source Type"
                label="Source type"
                options={componentState.sourceTypeList.filter(
                  (option) => option.showInDropdown
                )}
                value={componentState.sourceTypePreEvent}
                onChange={(e, item) =>
                  onFormChange(
                    item.key,
                    "sourceTypePreEvent",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.sourceTypePreEventError}
                selectedKey={componentState.sourceTypePreEvent}
                className="flex-grow-1 me-0 me-md-2"
                disabled={imageLayerId ? true : false}
              />
              <Dropdown
                placeholder="Select a Format"
                label="Format"
                options={[{ key: "tif", text: "Tif" }]}
                value={componentState.format}
                onChange={(e, item) =>
                  onFormChange(
                    item.key,
                    "format",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.formatError}
                selectedKey={componentState.format}
                className="flex-grow-1 mb-2"
                disabled={imageLayerId ? true : false}
              />
            </div>
          </div>

          <CreateEditImageLayerFormBuildingFootprints
            componentState={componentState}
            setComponentState={setComponentState}
            imageLayerId={imageLayerId}
          />

          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <PrimaryButton onClick={submit} disabled={isUploading}>
                Submit
              </PrimaryButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CreateEditImageLayerModal;
