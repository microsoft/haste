// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { useState, useEffect, useContext } from "react";
import ProjectRow from "./ProjectManagement/ProjectRow";
import ProjectsHeader from "./ProjectManagement/ProjectsHeader";
import NoResults from "./ProjectManagement/NoResults";
import SectionHeader from "./Section/SectionHeader";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import { PrimaryButton, Text, IconButton, TextField, DefaultButton } from "@fluentui/react";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { apiGet } from "../util/api";
import PaginationControls from "./OtherComponents/PaginationControls";
import { AppContext } from "../AppContext";

const Projects = () => {
  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams } = useContext(AppContext);
  const [modalComponent, setModalComponent] = useState();
  const [items, setItems] = useState(null);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Search state
  const [searchText, setSearchText] = useState("");

  useEffect(() => {
    setCurrentPage(1);
  }, [appParams.userSettings.itemsPerPage]);

  useEffect(() => {
    initComponent();
    return () => {
      initCurrentTour(null);
      initGuidedTourState("projectsGuide", appParams.guidedTourProperties);
      setAppHeaderRightButtons([]);
      setModalComponent(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function handleResize() {
      if (appParams.bootstrapBreakpoint >= 3) {
        setMoreInfoVisibleId(null);
      }
    }
    window.addEventListener("resize", handleResize);
    handleResize();
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [appParams.bootstrapBreakpoint]);

  async function initComponent() {
    setIsLoading(true);
    await apiGet("GetDashboardData")
      .then((response) => {
        setItems(response);
        setCurrentPage(1); // Reset to first page on reload
        initGuidedTourState("projectsGuide", appParams.guidedTourProperties);
        initCurrentTour("projectsGuide");
        setAppHeaderRightButtons([
          {
            iconName: "help",
            title: "Help",
            id: "helpButton",
            onClick: () =>
              setGuidedTourState(false, initCurrentTour, "projectsGuide", appParams.guidedTourProperties),
          },
        ]);
      })
      .catch((error) => {
        console.error("Error fetching projects:", error);
      });
    setIsLoading(false);
  }

  if (!items) {
    return null;
  }

  // Filter projects by searchText
  const filteredProjects = items.projects.filter((project) => {
    if (!searchText) return true;
    const lowerSearch = searchText.toLowerCase();
    return Object.keys(project).some((key) => {
      const value = project[key];
      if (value == null) return false;
      return String(value).toLowerCase().includes(lowerSearch);
    });
  });

  // Pagination logic
  const totalProjects = filteredProjects.length;
  const PAGE_SIZE = appParams.userSettings.itemsPerPage ?? 10;
  const totalPages = Math.ceil(totalProjects / PAGE_SIZE);
  const paginatedProjects = filteredProjects.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const sectionHeaderProperties = {
    iconName: "FolderHorizontal",
    path: [{ name: "Projects", link: "" }],
    links: items.projects.length > 0
      ? [
        {
          name: "Start a Project",
          type: "function",
          id: "projectsStartProject",
          link: () => {
            setModalComponent(
              <CreateEditProjectModal onClose={() => setModalComponent(null)} />
            );
          },
        },
      ]
      : [],
    filter: true,
  };

  return (
    <>
      {items && (
        <div className="d-flex flex-column w-100 mb-5">
          <SectionHeader properties={sectionHeaderProperties} searchText={searchText} setSearchText={setSearchText} setCurrentPage={setCurrentPage} />
          <div className="container p-md-0">
            <div className="row m-0 p-0 pt-5">
              <div className="col-12" style={{ overflowX: "auto" }}>
                <table className="col-12 dashboard-table">
                  <ProjectsHeader />
                  <tbody>
                    {paginatedProjects.map((item, index) => (
                      <ProjectRow
                        item={item}
                        index={(currentPage - 1) * PAGE_SIZE + index}
                        key={item.id || index}
                        setModalComponent={setModalComponent}
                        fetchProjects={initComponent}
                        moreInfoVisibleId={moreInfoVisibleId}
                        setMoreInfoVisibleId={setMoreInfoVisibleId}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <NoResults items={filteredProjects} text={"No projects found"} />

            {items.projects.length === 0 && (
              <div className="col-12 d-flex justify-content-center align-items-center mt-3">
                <PrimaryButton
                  id="projectsStartProject"
                  text="Start Project"
                  onClick={() => {
                    setModalComponent(
                      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
                    );
                  }}
                  className="btn-primary"
                />
              </div>
            )}

            {/* Pagination Controls */}
            <PaginationControls totalPages={totalPages} currentPage={currentPage} setCurrentPage={setCurrentPage} />
          </div>
        </div>
      )}

      {modalComponent}
    </>
  );
};

export default Projects;
