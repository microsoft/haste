// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import React, { useContext, useRef, useMemo, Fragment } from "react";
import {
  Button,
  SearchBox,
  Tooltip,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItemRadio,
  MenuItemCheckbox,
  Dropdown,
  Option,
  Toast,
  ToastBody,
  ToastTitle,
  useToastController,
} from "@fluentui/react-components";
import { useParams } from "react-router-dom";
import { useState, useEffect } from "react";
import { apiGet } from "../util/api";
import { useNavigate } from "react-router-dom";

import LayerRow from "./ProjectManagement/LayerRow";
import LayerCard from "./ProjectManagement/LayerCard";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { FluentIcon } from "../util/icons";
import NoResultsMessage from "./NoResultsMessage";

import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";

import { AppContext } from "../AppContext";
import { updateUserSettings } from "../AppHelper";
import {
  collectProjectJobStates,
  findJobStatusTransitions,
} from "../util/jobNotifications";

import PropType from "prop-types";

const LAYER_COLUMNS = [
  { key: "name", label: "Name", sortable: true, sortKey: "name", always: true },
  { key: "status", label: "Status", sortable: true, sortKey: "status" },
  { key: "labeling", label: "Labeling", sortable: false },
  { key: "training", label: "Model Training", sortable: false },
  { key: "validation", label: "Building Validation", sortable: false },
  { key: "creator", label: "Creator", sortable: true, sortKey: "userId" },
  {
    key: "creationDate",
    label: "Creation Date",
    sortable: true,
    sortKey: "creationDate",
  },
];

const GROUP_OPTIONS = [
  { key: "none", label: "None" },
  { key: "status", label: "Status" },
  { key: "creator", label: "Creator" },
  { key: "source", label: "Source" },
];

const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];

/** Resolve the group bucket label for an image layer given the grouping. */
function getLayerGroupLabel(item, mode) {
  if (mode === "status") return item.status || "Unknown";
  if (mode === "creator") return item.userId || "Unknown";
  if (mode === "source") return item.sourceTypePostEvent || "Unspecified";
  return "";
}

const Project = ({ setModalComponent }) => {
  Project.propTypes = {
    setModalComponent: PropType.func.isRequired,
    modalComponent: PropType.element,
  };

  const projectId = useParams().projectId;
  const imageLayerId = useParams().imageLayerId;

  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams, setAppParams } = useContext(AppContext);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(
    appParams?.userSettings?.itemsPerPageLayers ?? 20
  );

  function resetPage() {
    setCurrentPage(1);
  }

  // Update the local page size and persist it to the global user setting so
  // the choice is reflected everywhere (mirrors the Settings modal).
  async function handlePageSizeChange(newSize) {
    setPageSize(newSize);
    resetPage();
    setIsLoading(true, "Updating Items Per Page...");
    const response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ itemsPerPageLayers: newSize }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        itemsPerPageLayers: newSize,
      },
    }));
    setIsLoading(false);
  }

  const [searchText, setSearchText] = useState("");
  const [sort, setSort] = useState({ key: "creationDate", dir: "desc" });
  const [groupBy, setGroupBy] = useState("none");
  const [visibleColumns, setVisibleColumns] = useState(
    LAYER_COLUMNS.map((c) => c.key)
  );
  const [viewMode, setViewMode] = useState(
    () => localStorage.getItem("haste-project-view") || "list"
  );
  const isMobileLayout = appParams.bootstrapBreakpoint < 4;
  const effectiveViewMode = isMobileLayout ? "cards" : viewMode;
  const effectiveGroupBy =
    effectiveViewMode === "cards" ? "none" : groupBy;

  const changeView = (mode) => {
    setViewMode(mode);
    localStorage.setItem("haste-project-view", mode);
  };

  const defaultProjectDetailsRef = useRef(null);
  const projectJobStatesRef = useRef(null);
  const { dispatchToast } = useToastController("job-completion-toaster");


  useEffect(() => {
    setCurrentPage(1);
  }, [appParams.userSettings.itemsPerPageLayers]);

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
        const currentJobStates = collectProjectJobStates(response);
        if (projectJobStatesRef.current) {
          for (const transition of findJobStatusTransitions(
            projectJobStatesRef.current,
            currentJobStates
          )) {
            const succeeded = transition.status === "Processed";
            dispatchToast(
              <Toast>
                <ToastTitle>{`${transition.title} ${succeeded ? "completed" : transition.status.toLowerCase()}`}</ToastTitle>
                <ToastBody>{transition.subject}</ToastBody>
              </Toast>,
              {
                intent: succeeded ? "success" : "error",
                timeout: 10000,
              }
            );
          }
        }
        projectJobStatesRef.current = currentJobStates;
        defaultProjectDetailsRef.current = response;
        setComponentState((prevState) => ({
          ...prevState,
          project: response,
          visibleModelId:
            prevState.visibleModelId !== "-1"
              ? prevState.visibleModelId
              : (response.imageLayer || []).find(
                  (layer) => layer.models && layer.models.length > 0
                )?.imageLayerId ?? "-1",
          sectionHeaderProperties: {
            iconName: "OpenFolderHorizontal",
            path: [
              { name: "Projects", link: "/projects" },
              { name: response.name, link: "" },
            ],
            links: [],
            filter: false,
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
    setComponentState((prevState) => {
      let nextValue = value;
      // Toggle the open model list for a given layer.
      if (key === "visibleModelId" && prevState.visibleModelId === value) {
        nextValue = "-1";
      }
      return { ...prevState, [key]: nextValue };
    });
  }

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  // Filter + sort + group the image layers (memoised so pagination is cheap).
  const imageLayers = componentState.project?.imageLayer || [];
  const processed = useMemo(() => {
    const search = searchText.toLowerCase();
    const filtered = imageLayers.filter(
      (layer) =>
        !search ||
        (layer.name && layer.name.toLowerCase().includes(search))
    );
    const dir = sort.dir === "asc" ? 1 : -1;
    const sorted = [...filtered].sort((a, b) => {
      // Keep group buckets contiguous when grouping is active.
      if (effectiveGroupBy !== "none") {
        const ga = getLayerGroupLabel(a, effectiveGroupBy);
        const gb = getLayerGroupLabel(b, effectiveGroupBy);
        if (ga !== gb) {
          return String(ga).localeCompare(String(gb));
        }
      }
      const col = LAYER_COLUMNS.find((c) => c.key === sort.key);
      const sortKey = col?.sortKey || sort.key;
      const av = a[sortKey];
      const bv = b[sortKey];
      return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
    });
    return sorted;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageLayers, searchText, sort, effectiveGroupBy]);

  if (!componentState.project) {
    return null;
  }

  // Pagination
  const total = processed.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(currentPage, totalPages);
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const paginated = processed.slice((page - 1) * pageSize, page * pageSize);
  const isEmpty = componentState.project.imageLayer.length === 0;
  const hasNoResults = !isEmpty && paginated.length === 0;

  const activeColumns = LAYER_COLUMNS.filter((c) =>
    visibleColumns.includes(c.key)
  );
  const optionalColumnKeys = activeColumns
    .filter((c) => c.key !== "name")
    .map((c) => c.key);

  const eventTypes = defaultProjectDetailsRef.current?.eventTypes
    ? defaultProjectDetailsRef.current.eventTypes
    : [];

  return (
    <React.Fragment key={projectId}>
      <div className="d-flex flex-column w-100">
        <div className="pgrid-page pgrid-page--layers">
          {/* Header */}
          <div className="pgrid-header">
            <div>
              <h1 className="pgrid-title">
                Image Layers
              </h1>
              <div className="pgrid-subtitle">
                Manage imagery, labeling, training, and validation for this
                project.
              </div>
              {componentState.sectionHeaderProperties?.path && (
                <nav className="pgrid-breadcrumb" aria-label="Breadcrumb">
                  {componentState.sectionHeaderProperties.path.map(
                    (crumb, i, arr) => (
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
                          <span
                            className="pgrid-breadcrumb-sep"
                            aria-hidden="true"
                          >
                            /
                          </span>
                        )}
                      </span>
                    )
                  )}
                  <Tooltip
                    content="Edit project properties"
                    relationship="label"
                  >
                    <button
                      type="button"
                      className="pgrid-breadcrumb-edit"
                      aria-label="Edit project properties"
                      onClick={() =>
                        setModalComponent(
                          <CreateEditProjectModal
                            onClose={() => {
                              setModalComponent(null);
                              fetchProjectDetails(false);
                            }}
                            projectId={projectId}
                          />
                        )
                      }
                    >
                      <FluentIcon name="Edit" />
                    </button>
                  </Tooltip>
                </nav>
              )}
            </div>
            {!isEmpty && (
              <Button
                id="singleProjectCreateImageLayer"
                className="pgrid-new-btn"
                appearance="primary"
                icon={<FluentIcon name="FileImage" />}
                onClick={() => navigate("/create-imageLayer/" + projectId)}
              >
                New Image Layer
              </Button>
            )}
          </div>

          {isEmpty ? (
            <div className="pgrid-empty">
              <FluentIcon name="FileImage" style={{ fontSize: 32 }} />
              <div>
                No image layers yet. Add imagery to start labeling and training.
              </div>
              <Button
                appearance="primary"
                icon={<FluentIcon name="FileImage" />}
                onClick={() => navigate("/create-imageLayer/" + projectId)}
              >
                New Image Layer
              </Button>
            </div>
          ) : (
            <>
              {/* Toolbar */}
              <div className="pgrid-toolbar">
                <SearchBox
                  className="pgrid-search"
                  placeholder="Search"
                  value={searchText}
                  onChange={(_, data) => {
                    setSearchText(data.value || "");
                    setCurrentPage(1);
                  }}
                />
                {effectiveViewMode === "list" && (
                  <Menu
                    checkedValues={{ group: [groupBy] }}
                    onCheckedValueChange={(_, { checkedItems }) =>
                      setGroupBy(checkedItems[0])
                    }
                  >
                    <MenuTrigger disableButtonEnhancement>
                      <Button icon={<FluentIcon name="GroupList" />}>
                        {`Group by: ${
                          (
                            GROUP_OPTIONS.find((o) => o.key === groupBy) ||
                            GROUP_OPTIONS[0]
                          ).label
                        }`}
                      </Button>
                    </MenuTrigger>
                    <MenuPopover>
                      <MenuList>
                        {GROUP_OPTIONS.map((opt) => (
                          <MenuItemRadio
                            key={opt.key}
                            name="group"
                            value={opt.key}
                          >
                            {opt.label}
                          </MenuItemRadio>
                        ))}
                      </MenuList>
                    </MenuPopover>
                  </Menu>
                )}
                <div className="pgrid-toolbar-spacer" />
                {!isMobileLayout && <div
                  className={`pgrid-toolbar-controls ${
                    effectiveViewMode === "list"
                      ? "pgrid-toolbar-controls--list"
                      : ""
                  }`}
                >
                  <div className="pgrid-view-toggle">
                    <Button
                      appearance="subtle"
                      className={effectiveViewMode === "list" ? "pgrid-view-active" : ""}
                      icon={<FluentIcon name="BulletedList" />}
                      title="List view"
                      aria-label="List view"
                      onClick={() => changeView("list")}
                    />
                    <Button
                      appearance="subtle"
                      className={effectiveViewMode === "cards" ? "pgrid-view-active" : ""}
                      icon={<FluentIcon name="GridViewSmall" />}
                      title="Grid view"
                      aria-label="Grid view"
                      onClick={() => changeView("cards")}
                    />
                  </div>
                  {effectiveViewMode === "list" && (
                    <Menu
                      checkedValues={{ columns: visibleColumns }}
                      onCheckedValueChange={(_, { checkedItems }) =>
                        setVisibleColumns(
                          LAYER_COLUMNS.filter(
                            (c) => c.always || checkedItems.includes(c.key)
                          ).map((c) => c.key)
                        )
                      }
                    >
                      <MenuTrigger disableButtonEnhancement>
                        <Button
                          className="pgrid-customize-btn"
                          icon={<FluentIcon name="ColumnOptions" />}
                        >
                          Customize Columns
                        </Button>
                      </MenuTrigger>
                      <MenuPopover>
                        <MenuList>
                          {LAYER_COLUMNS.map((col) => (
                            <MenuItemCheckbox
                              key={col.key}
                              name="columns"
                              value={col.key}
                              disabled={col.always}
                            >
                              {col.label}
                            </MenuItemCheckbox>
                          ))}
                        </MenuList>
                      </MenuPopover>
                    </Menu>
                  )}
                </div>}
              </div>

              {effectiveViewMode === "list" ? (
                <div className="pgrid-table-wrap">
                  {hasNoResults ? (
                    <NoResultsMessage
                      title="No image layers found"
                      fallbackMessage="No image layers match your filters."
                      searchText={searchText}
                      onClear={() => {
                        setSearchText("");
                        resetPage();
                      }}
                    />
                  ) : (
                    <table className="pgrid-table">
                      <thead id="singleProjectTable">
                        <tr>
                          <th className="pgrid-th-actions" />
                          {activeColumns.map((col) => (
                            <th key={col.key}>
                              <span
                                className={`pgrid-th-inner ${
                                  col.sortable ? "pgrid-th-sortable" : ""
                                }`}
                                onClick={() =>
                                  col.sortable && toggleSort(col.key)
                                }
                                role={col.sortable ? "button" : undefined}
                                tabIndex={col.sortable ? 0 : undefined}
                                onKeyDown={(e) => {
                                  if (
                                    col.sortable &&
                                    (e.key === "Enter" || e.key === " ")
                                  ) {
                                    toggleSort(col.key);
                                  }
                                }}
                              >
                                {col.label}
                                {sort.key === col.key && (
                                  <FluentIcon
                                    name={
                                      sort.dir === "asc" ? "SortUp" : "SortDown"
                                    }
                                    className="pgrid-sort-icon"
                                  />
                                )}
                              </span>
                            </th>
                          ))}
                          <th className="pgrid-th-actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {paginated.map((item, idx) => {
                          const absoluteIndex = (page - 1) * pageSize + idx;
                          const groupVal =
                            effectiveGroupBy !== "none"
                              ? getLayerGroupLabel(item, effectiveGroupBy)
                              : null;
                          const prevGroupVal =
                            effectiveGroupBy !== "none" && idx > 0
                              ? getLayerGroupLabel(
                                paginated[idx - 1],
                                effectiveGroupBy
                              )
                              : null;
                          const showGroupHeader =
                            effectiveGroupBy !== "none" &&
                            groupVal !== prevGroupVal;
                          return (
                            <Fragment key={item.imageLayerId || absoluteIndex}>
                              {showGroupHeader && (
                                <tr className="pgrid-group-row">
                                  <td colSpan={activeColumns.length + 2}>
                                    {groupVal}
                                  </td>
                                </tr>
                              )}
                              <LayerRow
                                item={item}
                                index={absoluteIndex}
                                columns={optionalColumnKeys}
                                visibleModelId={componentState.visibleModelId}
                                projectId={componentState.project.projectId}
                                onComponentChange={onComponentChange}
                                setModalComponent={setModalComponent}
                                fetchProjectDetails={fetchProjectDetails}
                                setComponentState={setComponentState}
                                eventTypes={eventTypes}
                              />
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              ) : (
                <div className="pcard-grid-wrap">
                  {hasNoResults ? (
                    <NoResultsMessage
                      title="No image layers found"
                      fallbackMessage="No image layers match your filters."
                      searchText={searchText}
                      onClear={() => {
                        setSearchText("");
                        resetPage();
                      }}
                    />
                  ) : (
                    <div className="pcard-grid">
                      {paginated.map((item, idx) => (
                        <LayerCard
                          key={item.imageLayerId || idx}
                          item={item}
                          index={(page - 1) * pageSize + idx}
                          projectId={componentState.project.projectId}
                          setModalComponent={setModalComponent}
                          fetchProjectDetails={fetchProjectDetails}
                          setComponentState={setComponentState}
                          eventTypes={eventTypes}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Footer */}
              <div className="pgrid-footer">
                <div>
                  Showing {start}–{end} of {total}
                </div>
                <div className="pgrid-footer-pagination">
                  <button
                    type="button"
                    className="pgrid-page-btn"
                    disabled={page <= 1}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  >
                    <FluentIcon
                      name="ArrowLeft"
                      className="pgrid-page-btn-icon"
                    />
                    Previous
                  </button>
                  <span className="pgrid-footer-page">
                    Page <b>{page}</b> of {totalPages}
                  </span>
                  <button
                    type="button"
                    className="pgrid-page-btn"
                    disabled={page >= totalPages}
                    onClick={() =>
                      setCurrentPage((p) => Math.min(totalPages, p + 1))
                    }
                  >
                    Next
                    <FluentIcon
                      name="ArrowRight"
                      className="pgrid-page-btn-icon"
                    />
                  </button>
                </div>
                <div className="pgrid-footer-rows">
                  <span>Rows per page:</span>
                  <Dropdown
                    className="pgrid-rows-dropdown"
                    style={{ minWidth: "72px" }}
                    size="small"
                    value={String(pageSize)}
                    selectedOptions={[String(pageSize)]}
                    onOptionSelect={(_, data) => {
                      handlePageSizeChange(Number(data.optionValue));
                    }}
                  >
                    {PAGE_SIZE_OPTIONS.map((size) => (
                      <Option key={size} value={String(size)}>
                        {String(size)}
                      </Option>
                    ))}
                  </Dropdown>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </React.Fragment>
  );
};

export default Project;

