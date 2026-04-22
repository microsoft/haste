// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import React, { useContext, useRef } from "react";
import { PrimaryButton, IconButton, Text } from "@fluentui/react"; // <-- Added IconButton, Text
import { useParams } from "react-router-dom";
import { useState, useEffect } from "react";
import { apiGet } from "../util/api";
import { useNavigate } from "react-router-dom";

import LayerRow from "./ProjectManagement/LayerRow";
import SectionHeader from "./Section/SectionHeader";
import ProjectHeader from "./ProjectManagement/ProjectHeader";
import PaginationControls from "./OtherComponents/PaginationControls";

import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";

import NoResults from "./ProjectManagement/NoResults";
import { AppContext } from "../AppContext";

import PropType from "prop-types";

const Project = ({ setModalComponent }) => {
  Project.propTypes = {
    setModalComponent: PropType.func.isRequired,
    modalComponent: PropType.element,
  };

  const projectId = useParams().projectId;
  const imageLayerId = useParams().imageLayerId;

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  const [searchText, setSearchText] = useState("");

  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams } = useContext(AppContext);
  const defaultProjectDetailsRef = useRef(null);

  useEffect(() => {
    setCurrentPage(1);
  }, [appParams.userSettings.itemsPerPage]);

  const DEFAULT_COMPONENT_STATE = {
    project: null,
    visibleModelId: imageLayerId || "-1",
    sectionHeaderProperties: null,
  };

  const projectCurrentTouruseRef = useRef(DEFAULT_COMPONENT_STATE.visibleModelId === "-1" ? "singleProjectGuide" : "singleProjectModelGuide");

  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);
  const [componentState, setComponentState] = useState(DEFAULT_COMPONENT_STATE);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      await fetchProjectDetails();
    };
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageLayerId]);

  useEffect(() => {
    const fetchData = async () => {
      await fetchProjectDetails();

      initGuidedTourState(projectCurrentTouruseRef.current, appParams.guidedTourProperties);
      initCurrentTour(projectCurrentTouruseRef.current);

      setAppHeaderRightButtons([
        {
          iconName: "help",
          title: "Help",
          id: "helpButton",
          onClick: () =>
            setGuidedTourState(false, initCurrentTour, projectCurrentTouruseRef.current, appParams.guidedTourProperties),
        },
      ]);
    };
    fetchData();

    //On component dismount
    return () => {
      initCurrentTour(null);
      initGuidedTourState(projectCurrentTouruseRef.current, appParams.guidedTourProperties);
      setAppHeaderRightButtons([]);
      setModalComponent(null);
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (componentState.visibleModelId === "-1") {
      projectCurrentTouruseRef.current = "singleProjectGuide";
    } else {
      projectCurrentTouruseRef.current = "singleProjectModelGuide";
    }
  }, [componentState.visibleModelId]);

  async function fetchProjectDetails(showLoading = true) {
    if (showLoading) {
      setIsLoading(true);
    }
    await apiGet("GetProjectDetails?projectId=" + projectId + "&includeModels=True")
      .then((response) => {
        defaultProjectDetailsRef.current = response;
        setComponentState((prevState) => ({
          ...prevState,
          project: response,
          sectionHeaderProperties: {
            iconName: "OpenFolderHorizontal",
            path: [
              { name: "Projects", link: "/projects" },
              { name: response.name, link: "" },
            ],
            links:
              response.imageLayer.length > 0
                ? [
                  {
                    name: "Create Image Layer",
                    id: "singleProjectCreateImageLayer",
                    type: "function",
                    link: () => {
                      navigate("/create-imageLayer/" + projectId);
                    },
                  },
                ]
                : [],
            filter: true,
          },
        }));
      })
      .catch((error) => {
        console.error("Error fetching projects:", error);
      });
    if (showLoading) {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    const intervalId = setInterval(async () => {
      fetchProjectDetails(false);
    }, 20000);

    return () => clearInterval(intervalId);

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    function handleResize() {
      if (appParams.bootstrapBreakpoint >= 4) {
        setMoreInfoVisibleId(null);
      }
    }

    window.addEventListener("resize", handleResize);

    // Initial check in case the component mounts with width > 992
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [appParams.bootstrapBreakpoint]);


  function onComponentChange(value, key) {
    // To close the model list for a given layer if it is already open
    if (key === "visibleModelId") {
      if (componentState.visibleModelId === value) {
        value = "-1";
      }
    }

    setComponentState({ ...componentState, [key]: value });
  }

  if (!componentState.project) {
    return null;
  }

  // PAGINATION LOGIC
  const imageLayers = componentState.project?.imageLayer || [];
  const filteredImageLayers = imageLayers.filter(
    (layer) =>
      !searchText ||
      (layer.name && layer.name.toLowerCase().includes(searchText.toLowerCase()))
  );
  const totalPages = Math.ceil(filteredImageLayers.length / (appParams.userSettings.itemsPerPage ?? 10)) || 1;
  const pagedImageLayers = filteredImageLayers.slice(
    (currentPage - 1) * (appParams.userSettings.itemsPerPage ?? 10),
    currentPage * (appParams.userSettings.itemsPerPage ?? 10)
  );

  return (
    <React.Fragment key={projectId}>
      <div className="d-flex flex-column w-100 mb-5">
        <SectionHeader properties={componentState.sectionHeaderProperties} searchText={searchText} setSearchText={setSearchText} setCurrentPage={setCurrentPage} />
        <div className="container p-md-0">
          <div className="row m-0 p-0 pt-5">
            <div className="col-12" style={{ overflowX: "auto" }}>
              <table className="col-12 dashboard-table">
                <ProjectHeader />
                <tbody>
                  {pagedImageLayers.map((item, index) => (
                    <LayerRow
                      key={index + (currentPage - 1) * (appParams.userSettings.itemsPerPage ?? 10)}
                      item={item}
                      index={index + (currentPage - 1) * (appParams.userSettings.itemsPerPage ?? 10)}
                      visibleModelId={componentState.visibleModelId}
                      projectId={componentState.project.projectId}
                      onComponentChange={onComponentChange}
                      setModalComponent={setModalComponent}
                      fetchProjectDetails={fetchProjectDetails}
                      setComponentState={setComponentState}
                      eventTypes={defaultProjectDetailsRef.current.eventTypes ? defaultProjectDetailsRef.current.eventTypes : []}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <NoResults
            items={pagedImageLayers}
            text={"No image layers found"}
          />

          {componentState.project.imageLayer.length === 0 && (
            <div className="col-12 d-flex justify-content-center align-items-center mt-3">
              <PrimaryButton
                id="singleProjectCreateImageLayer"
                text="Create Image Layer"
                onClick={() => {
                  navigate("/create-imageLayer/" + projectId);
                }}
                className="btn-primary"
              />
            </div>
          )}

          {/* Pagination Controls */}
          <PaginationControls totalPages={totalPages} currentPage={currentPage} setCurrentPage={setCurrentPage} />

        </div>
      </div>
    </React.Fragment>
  );
};

export default Project;
