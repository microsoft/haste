// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext, useEffect } from "react";
import { DatePicker } from "@fluentui/react-datepicker-compat";
import {
  Input,
  Textarea,
  Button,
  Text,
  Dropdown,
  Option,
  Field,
  Tooltip,
} from "@fluentui/react-components";

import { useParams } from "react-router-dom";
import { FluentIcon } from "../util/icons";
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
      workflowType,
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
          workflowType: workflowType || "standard",
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

  const headerPath = componentState.sectionHeaderProperties?.path;
  const currentCrumbLabel = componentState.name?.trim() || "New Image Layer";
  const displayHeaderPath = headerPath
    ? headerPath.map((crumb, i, arr) =>
        i === arr.length - 1 ? { ...crumb, name: currentCrumbLabel } : crumb
      )
    : headerPath;

  return (
    <div className="d-flex flex-column w-100">
      <div className="pgrid-page pgrid-page--scroll">
        {/* Header */}
        <div className="pgrid-header">
          <div>
            <h1 className="pgrid-title">
              {imageLayerId ? "Edit Image Layer" : "New Image Layer"}
              <Tooltip
                content="Define imagery sources, capture dates, and building footprints for this image layer."
                relationship="label"
              >
                <span>
                  <FluentIcon name="Info" className="pgrid-title-info" />
                </span>
              </Tooltip>
            </h1>
            <div className="pgrid-subtitle">
              Define imagery sources, capture dates, and building footprints
              for this image layer.
            </div>
            {headerPath && (
              <nav className="pgrid-breadcrumb" aria-label="Breadcrumb">
                {displayHeaderPath.map((crumb, i, arr) => (
                  <span key={i} className="pgrid-breadcrumb-item">
                    {crumb.link ? (
                      <button
                        type="button"
                        className="pgrid-breadcrumb-link"
                        onClick={() => navigate(crumb.link)}
                      >
                        {crumb.name}
                      </button>
                    ) : (
                      <span className="pgrid-breadcrumb-current">
                        {crumb.name}
                      </span>
                    )}
                    {i < arr.length - 1 && (
                      <span className="pgrid-breadcrumb-sep" aria-hidden="true">
                        /
                      </span>
                    )}
                  </span>
                ))}
              </nav>
            )}
          </div>
        </div>
        <div className="pgrid-form-body">
          <div className="container d-flex justify-content-center">
            <div className="col-12 col-md-9 col-lg-8 col-xl-6">
          <div className="row mb-2">
            <div className="col-12">
              <Field label="Name" required validationMessage={componentState.nameError}>
                <Input
                  id="createEditImageLayerName"
                  maxLength={250}
                  onChange={(e, data) =>
                    onFormChange(
                      data.value,
                      "name",
                      setComponentState,
                      componentState
                    )
                  }
                  value={componentState.name}
                />
              </Field>
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12">
              <Field
                label="Description"
                hint={
                  componentState.description.length + "/2000 " + "characters"
                }
              >
                <Textarea
                  id="createEditImageLayerDescription"
                  rows={5}
                  maxLength={2000}
                  onChange={(e, data) =>
                    onFormChange(
                      data.value,
                      "description",
                      setComponentState,
                      componentState
                    )
                  }
                  value={componentState.description}
                />
              </Field>
            </div>
          </div>

          <div className="row mb-2">
            <div className="col-12">
              <Field label="Workflow type">
                <Dropdown
                  id="createEditImageLayerWorkflowType"
                  selectedOptions={[
                    String(componentState.workflowType || "standard"),
                  ]}
                  value={
                    (componentState.workflowType || "standard") === "building"
                      ? "Building labeling workflow"
                      : "Standard labeling workflow"
                  }
                  onOptionSelect={(e, data) =>
                    onFormChange(
                      data.optionValue,
                      "workflowType",
                      setComponentState,
                      componentState
                    )
                  }
                >
                  <Option value="standard">Standard labeling workflow</Option>
                  <Option value="building">Building labeling workflow</Option>
                </Dropdown>
              </Field>
            </div>
          </div>

          <div className="row mb-2 p-2">
            <div className="col-12 p-4  flex-column d-flex box-highlight">
              <div className="col-12">
                <h6 className="m-0 pb-2">Imagery Details</h6>
                <Text>
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
                <Text className="">
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
                aria-label="Select a date"
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
                value={
                  componentState.imageryCaptureDatePostEvent !== ""
                    ? new Date(componentState.imageryCaptureDatePostEvent)
                    : null
                }
                disabled={imageLayerId ? true : false}
              />
              <Field
                label="Source type"
                className="flex-grow-1 me-0 me-md-2"
                validationMessage={componentState.sourceTypePostEventError}
              >
                <Dropdown
                  id="createEditImageLayerPostEventSourceType"
                  placeholder="Select a Source Type"
                  selectedOptions={[String(componentState.sourceTypePostEvent ?? "")]}
                  value={
                    componentState.sourceTypeList.find(
                      (o) => o.key === componentState.sourceTypePostEvent
                    )?.text || ""
                  }
                  onOptionSelect={(e, data) =>
                    onFormChange(
                      data.optionValue,
                      "sourceTypePostEvent",
                      setComponentState,
                      componentState
                    )
                  }
                  disabled={imageLayerId ? true : false}
                >
                  {componentState.sourceTypeList
                    .filter((option) => option.showInDropdown)
                    .map((option) => (
                      <Option key={option.key} value={String(option.key)}>
                        {option.text}
                      </Option>
                    ))}
                </Dropdown>
              </Field>
              <Field
                label="Format"
                className="flex-grow-1 mb-2"
                validationMessage={componentState.formatError}
              >
                <Dropdown
                  placeholder="Select a Format"
                  selectedOptions={[String(componentState.format ?? "")]}
                  value={componentState.format === "tif" ? "Tif" : ""}
                  onOptionSelect={(e, data) =>
                    onFormChange(
                      data.optionValue,
                      "format",
                      setComponentState,
                      componentState
                    )
                  }
                  disabled={imageLayerId ? true : false}
                >
                  <Option value="tif">Tif</Option>
                </Dropdown>
              </Field>
            </div>
          </div>

          <div className="row mb-2 p-2">
            <div className="col-12 p-4 pb-0 flex-column d-flex box-highlight">
              <div className="col-12 mb-4">
                <h6 className="m-0 pb-3">Pre-Event Imagery</h6>
                <Text>
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
                aria-label="Select a date"
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
                    : null
                }
                disabled={imageLayerId ? true : false}
              />
              <Field
                label="Source type"
                className="flex-grow-1 me-0 me-md-2"
                validationMessage={componentState.sourceTypePreEventError}
              >
                <Dropdown
                  id="createEditImageLayerPreEventSourceType"
                  placeholder="Select a Source Type"
                  selectedOptions={[String(componentState.sourceTypePreEvent ?? "")]}
                  value={
                    componentState.sourceTypeList.find(
                      (o) => o.key === componentState.sourceTypePreEvent
                    )?.text || ""
                  }
                  onOptionSelect={(e, data) =>
                    onFormChange(
                      data.optionValue,
                      "sourceTypePreEvent",
                      setComponentState,
                      componentState
                    )
                  }
                  disabled={imageLayerId ? true : false}
                >
                  {componentState.sourceTypeList
                    .filter((option) => option.showInDropdown)
                    .map((option) => (
                      <Option key={option.key} value={String(option.key)}>
                        {option.text}
                      </Option>
                    ))}
                </Dropdown>
              </Field>
              <Field
                label="Format"
                className="flex-grow-1 mb-2"
                validationMessage={componentState.formatError}
              >
                <Dropdown
                  placeholder="Select a Format"
                  selectedOptions={[String(componentState.format ?? "")]}
                  value={componentState.format === "tif" ? "Tif" : ""}
                  onOptionSelect={(e, data) =>
                    onFormChange(
                      data.optionValue,
                      "format",
                      setComponentState,
                      componentState
                    )
                  }
                  disabled={imageLayerId ? true : false}
                >
                  <Option value="tif">Tif</Option>
                </Dropdown>
              </Field>
            </div>
          </div>

          <CreateEditImageLayerFormBuildingFootprints
            componentState={componentState}
            setComponentState={setComponentState}
            imageLayerId={imageLayerId}
          />

          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <Button appearance="primary" onClick={submit} disabled={isUploading}>
                Submit
              </Button>
            </div>
          </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CreateEditImageLayerModal;
