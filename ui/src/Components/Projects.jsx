// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { useState, useEffect, useContext, useMemo, Fragment } from "react";
import ProjectRow from "./ProjectManagement/ProjectRow";
import ProjectCard from "./ProjectManagement/ProjectCard";
import { getProjectStatus } from "./ProjectManagement/projectStatus";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import {
  Button,
  SplitButton,
  SearchBox,
  Dropdown,
  Option,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
  MenuItemCheckbox,
  MenuItemRadio,
  Tooltip,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import CreateEditProjectModal from "./CreateEditProjectModal";
import NoResultsMessage from "./NoResultsMessage";
import { apiGet } from "../util/api";
import { loadCountryNames } from "../util/countries";
import { AppContext } from "../AppContext";
import { updateUserSettings } from "../AppHelper";

const ALL_COLUMNS = [
  { key: "name", label: "Name", sortable: true, always: true },
  { key: "description", label: "Description", sortable: true },
  { key: "createdBy", label: "Created By", sortable: true },
  { key: "affectedCountries", label: "Affected Countries", sortable: false },
  { key: "imageLayerCount", label: "Image Layers", sortable: true, numeric: true },
  { key: "modelsCount", label: "Models", sortable: true, numeric: true },
  { key: "labelsCount", label: "Labels", sortable: true, numeric: true },
  { key: "creationDate", label: "Created", sortable: true },
];

const GROUP_OPTIONS = [
  { key: "none", label: "None" },
  { key: "year", label: "Date (year)" },
  { key: "country", label: "Affected Country" },
];

/** Resolve the group bucket label for a project given the active grouping. */
function getGroupLabel(item, mode, countryNames = {}) {
  if (mode === "year") {
    const d = item.creationDate;
    return d && d.length >= 4 ? d.substring(0, 4) : "Unknown";
  }
  if (mode === "country") {
    if (
      Array.isArray(item.affectedCountries) &&
      item.affectedCountries.length > 0
    ) {
      const countryCode = item.affectedCountries[0];
      return countryNames[countryCode] || countryCode;
    }
    return "Unspecified";
  }
  return "";
}

const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];

const Projects = () => {
  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams, setAppParams } =
    useContext(AppContext);
  const [modalComponent, setModalComponent] = useState();
  const [items, setItems] = useState(null);

  const [searchText, setSearchText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(
    appParams.userSettings.itemsPerPageProjects ?? 20
  );
  const [sort, setSort] = useState({ key: "creationDate", dir: "desc" });
  const [groupBy, setGroupBy] = useState("none");
  const [visibleColumns, setVisibleColumns] = useState(
    ALL_COLUMNS.map((c) => c.key)
  );
  const [countryNames, setCountryNames] = useState({});
  const [viewMode, setViewMode] = useState(() => {
    return localStorage.getItem("haste-projects-view") || "list";
  });
  const isMobile = appParams.bootstrapBreakpoint < 4;
  const effectiveViewMode = isMobile ? "cards" : viewMode;
  const effectiveGroupBy =
    effectiveViewMode === "cards" ? "none" : groupBy;

  const changeView = (mode) => {
    setViewMode(mode);
    localStorage.setItem("haste-projects-view", mode);
  };

  useEffect(() => {
    loadCountryNames().then(setCountryNames);
  }, []);

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

  async function initComponent() {
    setIsLoading(true);
    await apiGet("GetDashboardData")
      .then((response) => {
        setItems(response);
        setCurrentPage(1);
        initGuidedTourState("projectsGuide", appParams.guidedTourProperties);
        initCurrentTour("projectsGuide");
        setAppHeaderRightButtons([
          {
            iconName: "help",
            title: "Help",
            id: "helpButton",
            onClick: () =>
              setGuidedTourState(
                false,
                initCurrentTour,
                "projectsGuide",
                appParams.guidedTourProperties
              ),
          },
        ]);
      })
      .catch((error) => {
        console.error("Error fetching projects:", error);
      });
    setIsLoading(false);
  }

  const openCreateModal = () => {
    setModalComponent(
      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
    );
  };

  // Filtering + sorting (memoised so pagination is cheap)
  const processed = useMemo(() => {
    if (!items) return [];
    const search = searchText.toLowerCase();
    const filtered = items.projects.filter((project) => {
      if (!search) return true;
      return Object.keys(project).some((key) => {
        const value = project[key];
        if (value == null) return false;
        return String(value).toLowerCase().includes(search);
      });
    });

    const dir = sort.dir === "asc" ? 1 : -1;
    const sorted = [...filtered].sort((a, b) => {
      // Keep group buckets contiguous when grouping is active.
      if (effectiveGroupBy !== "none") {
        const ga = getGroupLabel(a, effectiveGroupBy, countryNames);
        const gb = getGroupLabel(b, effectiveGroupBy, countryNames);
        if (ga !== gb) {
          const cmp = String(ga).localeCompare(String(gb));
          return effectiveGroupBy === "year" ? -cmp : cmp;
        }
      }
      let av;
      let bv;
      if (sort.key === "status") {
        av = getProjectStatus(a).label;
        bv = getProjectStatus(b).label;
      } else {
        av = a[sort.key];
        bv = b[sort.key];
      }
      const col = ALL_COLUMNS.find((c) => c.key === sort.key);
      if (col && col.numeric) {
        return ((av ?? 0) - (bv ?? 0)) * dir;
      }
      return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
    });
    return sorted;
  }, [items, searchText, sort, effectiveGroupBy, countryNames]);

  const total = processed.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(currentPage, totalPages);
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const paginated = processed.slice((page - 1) * pageSize, page * pageSize);
  const hasNoResults = !!items && items.projects.length > 0 && paginated.length === 0;

  const activeColumns = ALL_COLUMNS.filter((c) =>
    visibleColumns.includes(c.key)
  );

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

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
    await updateUserSettings(response, [{ itemsPerPageProjects: newSize }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        itemsPerPageProjects: newSize,
      },
    }));
    setIsLoading(false);
  }

  if (!items) {
    return null;
  }

  const isEmpty = !items || items.projects.length === 0;

  return (
    <>
      <div className="pgrid-page pgrid-page--projects">
        {/* Header */}
        <div className="pgrid-header">
          <div>
            <h1 className="pgrid-title">
              Projects
            </h1>
            <div className="pgrid-subtitle">
              Browse, filter, and track disaster assessment projects.
            </div>
          </div>
          {!isEmpty && (
            <Button
              id="projectsStartProject"
              className="pgrid-new-btn"
              appearance="primary"
              icon={<FluentIcon name="FabricNewFolder" />}
              onClick={openCreateModal}
            >
              New Project
            </Button>
          )}
        </div>

        {/* Toolbar */}
        {!isEmpty && (
          <div className="pgrid-toolbar">
          <SearchBox
            className="pgrid-search"
            placeholder="Search"
            value={searchText}
            onChange={(_, data) => {
              setSearchText(data.value || "");
              resetPage();
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
                    <MenuItemRadio key={opt.key} name="group" value={opt.key}>
                      {opt.label}
                    </MenuItemRadio>
                  ))}
                </MenuList>
              </MenuPopover>
            </Menu>
          )}
          <div className="pgrid-toolbar-spacer" />
          <div
            className={`pgrid-toolbar-controls ${
              effectiveViewMode === "list"
                ? "pgrid-toolbar-controls--list"
                : ""
            }`}
          >
            {!isMobile && (
              <div className="pgrid-view-toggle">
                <Button
                  appearance="subtle"
                  className={viewMode === "list" ? "pgrid-view-active" : ""}
                  icon={<FluentIcon name="BulletedList" />}
                  title="List view"
                  aria-label="List view"
                  onClick={() => changeView("list")}
                />
                <Button
                  appearance="subtle"
                  className={viewMode === "cards" ? "pgrid-view-active" : ""}
                  icon={<FluentIcon name="GridViewSmall" />}
                  title="Grid view"
                  aria-label="Grid view"
                  onClick={() => changeView("cards")}
                />
              </div>
            )}
            {effectiveViewMode === "list" && (
              <Menu
                checkedValues={{ columns: visibleColumns }}
                onCheckedValueChange={(_, { checkedItems }) =>
                  setVisibleColumns(
                    ALL_COLUMNS.filter(
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
                    {ALL_COLUMNS.map((col) => (
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
          </div>
        </div>
        )}

        {isEmpty ? (
          <div className="pgrid-empty">
            <FluentIcon name="FolderHorizontal" style={{ fontSize: 32 }} />
            <div>No projects yet. Start your first assessment project.</div>
            <Button
              appearance="primary"
              icon={<FluentIcon name="Add" />}
              onClick={openCreateModal}
            >
              New Project
            </Button>
          </div>
        ) : (
          <>
            {effectiveViewMode === "list" ? (
            <div className="pgrid-table-wrap">
              {hasNoResults ? (
                <NoResultsMessage
                  title="No projects found"
                  fallbackMessage="No projects match your filters."
                  searchText={searchText}
                  onClear={() => {
                    setSearchText("");
                    resetPage();
                  }}
                />
              ) : (
                <table className="pgrid-table">
                  <thead id="projectsTable">
                    <tr>
                      {activeColumns.map((col) => (
                        <th
                          key={col.key}
                          className={col.numeric ? "pgrid-th-numeric" : ""}
                        >
                          <span
                            className={`pgrid-th-inner ${
                              col.sortable ? "pgrid-th-sortable" : ""
                            }`}
                            onClick={() => col.sortable && toggleSort(col.key)}
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
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
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
                    {paginated.map((item, index) => {
                      const groupVal =
                        effectiveGroupBy !== "none"
                          ? getGroupLabel(item, effectiveGroupBy, countryNames)
                          : null;
                      const prevGroupVal =
                        effectiveGroupBy !== "none" && index > 0
                          ? getGroupLabel(
                            paginated[index - 1],
                            effectiveGroupBy,
                            countryNames
                          )
                          : null;
                      const showGroupHeader =
                        effectiveGroupBy !== "none" && groupVal !== prevGroupVal;
                      return (
                        <Fragment key={item.projectId || index}>
                          {showGroupHeader && (
                            <tr className="pgrid-group-row">
                              <td colSpan={activeColumns.length + 1}>
                                {groupVal}
                              </td>
                            </tr>
                          )}
                          <ProjectRow
                            item={item}
                            index={(page - 1) * pageSize + index}
                            columns={activeColumns.map((c) => ({
                              key: c.key,
                              label: c.label,
                            }))}
                            countryNames={countryNames}
                            setModalComponent={setModalComponent}
                            fetchProjects={initComponent}
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
                  title="No projects found"
                  fallbackMessage="No projects match your filters."
                  searchText={searchText}
                  onClear={() => {
                    setSearchText("");
                    resetPage();
                  }}
                />
              ) : (
                <div className="pcard-grid">
                  {paginated.map((item, index) => (
                    <ProjectCard
                      key={item.projectId || index}
                      item={item}
                      index={(page - 1) * pageSize + index}
                      countryNames={countryNames}
                      setModalComponent={setModalComponent}
                      fetchProjects={initComponent}
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
                  <FluentIcon name="ArrowLeft" className="pgrid-page-btn-icon" />
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
                  <FluentIcon name="ArrowRight" className="pgrid-page-btn-icon" />
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

      {modalComponent}
    </>
  );
};

export default Projects;

