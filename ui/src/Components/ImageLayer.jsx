// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { useEffect, useState, useContext } from "react";
import { useParams } from "react-router-dom";

import SectionHeader from "./Section/SectionHeader";
import ModelRow from "./ProjectManagement/ModelRow";
import { apiGet } from "../util/api";

import { AppContext } from "../AppContext";

const ImageLayer = () => {
  const projectId = useParams().projectId;
  const imageLayerId = useParams().imageLayerId;

  const [selectedProject, setSelectedProject] = useState("");
  const [selectedImageLayer, setSelectedImageLayer] = useState("");
  const [sectionHeaderProperties, setSectionHeaderProperties] = useState();

  const { setIsLoading } = useContext(AppContext);

  useEffect(() => {
    const fetchProject = async () => {
      setIsLoading(true);
      try {
        const project = await apiGet(
          "GetProjectDetails?projectId=" + projectId + "&includeModels=True"
        );
        setSelectedProject(project);
        const imageLayer = project.imageLayer.find(
          (x) => x.imageLayerId === imageLayerId
        );
        setSelectedImageLayer(imageLayer);
        setSectionHeaderProperties({
          iconName: "OpenFolderHorizontal",
          path: [
            { name: "Projects", link: "/projects" },
            { name: project.name, link: "/project/" + project.projectId },
            { name: imageLayer.name, link: "" },
          ],
          links: [],
          filter: false,
          filterText: ":",
          filterButtonText: "",
          filterPlaceholder: "",
        });
      } catch (error) {
        console.error("Error fetching project:", error);
      }
      setIsLoading(false);
    };

    fetchProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!selectedProject || !selectedImageLayer) {
    return;
  }


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
