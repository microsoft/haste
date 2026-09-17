// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Button, MessageBar, MessageBarBody, Spinner } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import SectionHeader from "./Section/SectionHeader";
import ModelRow from "./ProjectManagement/ModelRow";
import { apiGet } from "../util/api";

const ImageLayer = () => {
  const { projectId, imageLayerId } = useParams();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const fetchProject = async () => {
      try {
        const query = new URLSearchParams({ projectId, includeModels: "True" });
        const project = await apiGet(
          `GetProjectDetails?${query}`,
          { signal: controller.signal }
        );
        controller.signal.throwIfAborted();
        const imageLayer = project.imageLayer?.find(
          (layer) => layer.imageLayerId === imageLayerId
        );
        if (!imageLayer) throw new Error("Image layer was not found.");
        setResult({ projectId, imageLayerId, attempt, project, imageLayer });
      } catch (error) {
        if (controller.signal.aborted || error.name === "AbortError") return;
        setResult({
          projectId,
          imageLayerId,
          attempt,
          error: "Image layer details could not be loaded.",
        });
      }
    };

    fetchProject();
    return () => controller.abort();
  }, [projectId, imageLayerId, attempt]);

  if (
    result?.projectId !== projectId ||
    result?.imageLayerId !== imageLayerId ||
    result?.attempt !== attempt
  ) {
    return (
      <div className="p-4 w-100" data-route-loading="true" aria-busy="true">
        <Spinner label="Loading image layer" />
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="p-4 w-100">
        <MessageBar intent="error">
          <MessageBarBody>{result.error}</MessageBarBody>
        </MessageBar>
        <Button className="mt-3" onClick={() => setAttempt((value) => value + 1)}>
          Retry
        </Button>
      </div>
    );
  }

  const { project: selectedProject, imageLayer: selectedImageLayer } = result;
  const sectionHeaderProperties = {
    iconName: "OpenFolderHorizontal",
    path: [
      { name: "Projects", link: "/projects" },
      { name: selectedProject.name, link: "/project/" + selectedProject.projectId },
      { name: selectedImageLayer.name, link: "" },
    ],
    links: [],
    filter: false,
    filterText: ":",
    filterButtonText: "",
    filterPlaceholder: "",
  };

  return (
    <>
      <div className="d-flex flex-column w-100">
        <SectionHeader properties={sectionHeaderProperties} />
        <div className="container p-0">
          <div className="row m-0 p-3 pt-5 gap-3 pe-0">
            {/* Image Preview */}
            <div
              className="col p-3 d-flex flex-column"
              style={{
                backgroundColor: "gray",
                borderRadius: "5px",
                aspectRatio: "1 / 1",
                justifyContent: "space-between",
              }}
            >
              <h5 style={{ color: "#FFFFFF" }}>Imagery Preview</h5>
              <div className="d-flex justify-content-between">
                <Button
                  appearance="subtle"
                  icon={<FluentIcon name="ChevronLeft" />}
                  aria-label="Previous"
                  style={{ color: "#FFFFFF" }}
                  className="mt-auto"
                />
                <Button
                  appearance="subtle"
                  icon={<FluentIcon name="ChevronRight" />}
                  aria-label="Next"
                  style={{ color: "#FFFFFF" }}
                  className="mt-auto"
                />
              </div>
              <div className="d-flex flex-row justify-content-end">
                <Button
                  appearance="transparent"
                  style={{ color: "#FFFFFF" }}
                  icon={<FluentIcon name="ScaleVolume" style={{ color: "#ffffff" }} />}
                  className="mt-auto"
                >
                  View More
                </Button>
              </div>
            </div>

            <div
              className="col-8 p-3"
              style={{
                backgroundColor: "#4E4E4E",
                borderRadius: "5px",
                color: "#FFFFFF",
              }}
            >
              <h5 style={{ color: "#FFFFFF" }}>{selectedImageLayer.name}</h5>
              <hr />
              {selectedImageLayer.description}
            </div>

            {/* Image Preview */}
            <div
              className="col p-3 d-flex flex-column"
              style={{
                backgroundColor: "var(--primary-color)",
                borderRadius: "5px",
                aspectRatio: "1 / 1",
                justifyContent: "space-between",
              }}
            >
              <h5 style={{ color: "#FFFFFF" }}>Labeling</h5>
              <div className="d-flex justify-content-center">
                <div>
                  <span
                    className="fw-semibold"
                    style={{ fontSize: "60px", color: "#FFFFFF" }}
                  >
                    {selectedImageLayer.labelProjectCount}
                  </span>
                  <span style={{ fontSize: "12px", color: "#FFFFFF" }}>
                    Labels
                  </span>
                </div>
              </div>
              <div className="d-flex flex-row justify-content-end">
                <Button className="mt-auto" disabled={selectedImageLayer.status !== "Processed"}>
                  Launch Labeling Tool
                </Button>
              </div>
            </div>
          </div>
          <div className="row m-0 p-0">
            <div className="col-12 p-0">
              <table className="w-100">
                <tr>
                  <td className="ps-3">
                    {selectedImageLayer.models && (
                      <table
                        className="col-12 dashboard-inner-table mt-2 p-3"
                        style={{
                          backgroundColor: "#FFFFFF",
                          border: "1px solid #999999",
                        }}
                      >
                        <tbody>
                          <ModelRow
                            models={selectedImageLayer.models}
                            imageLayerId={selectedImageLayer.imageLayerId}
                            projectId={projectId}
                            labelProjectCount={
                              selectedImageLayer.labelProjectCount
                            }
                            fetchProjectDetails={null}
                          />
                        </tbody>

                        <tr>
                          <td className="pt-3">
                            <Button
                              className="dashboard-button d-none"
                              disabled={
                                selectedImageLayer.status !== "Processed"
                              }
                            >
                              Train a Model
                            </Button>
                          </td>
                        </tr>
                      </table>
                    )}
                  </td>
                </tr>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default ImageLayer;
