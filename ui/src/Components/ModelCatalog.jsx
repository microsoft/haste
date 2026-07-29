// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { useState, useEffect, useContext } from "react";
import { Dropdown, Option, SearchBox, Tooltip } from "@fluentui/react-components";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import { apiGet } from "../util/api";
import { AppContext } from "../AppContext";
import ModelCatalogRow from "./ProjectManagement/ModelCatalogRow";
import NoResultsMessage from "./NoResultsMessage";
import { FluentIcon } from "../util/icons";
import { updateUserSettings } from "../AppHelper";

const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];

const ModelCatalog = () => {
  const {
    setIsLoading,
    initCurrentTour,
    setAppHeaderRightButtons,
    appParams,
    setAppParams,
  } = useContext(AppContext);
  const [modalComponent, setModalComponent] = useState();
  const [items, setItems] = useState(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(
    appParams.userSettings.itemsPerPageModelCatalog ?? 20
  );

  // Search state
  const [searchText, setSearchText] = useState("");
  const [sort, setSort] = useState({ key: "cataloguedDate", dir: "desc" });

  useEffect(() => {
    setCurrentPage(1);
    setPageSize(appParams.userSettings.itemsPerPageModelCatalog ?? 20);
  }, [appParams.userSettings.itemsPerPageModelCatalog]);

  useEffect(() => {
    initComponent();
    return () => {
      initCurrentTour(null);
      initGuidedTourState("modelCatalogGuide", appParams.guidedTourProperties);
      setAppHeaderRightButtons([]);
      setModalComponent(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function initComponent() {
    setIsLoading(true);
    await apiGet("GetModelCatalog")
      .then((response) => {
        setItems(response);
        setCurrentPage(1); // Reset to first page on reload
        initGuidedTourState("modelCatalogGuide", appParams.guidedTourProperties);
        initCurrentTour("modelCatalogGuide");
        setAppHeaderRightButtons([
          {
            iconName: "help",
            title: "Help",
            id: "helpButton",
            onClick: () =>
              setGuidedTourState(false, initCurrentTour, "modelCatalogGuide", appParams.guidedTourProperties),
          },
        ]);
      })
      .catch((error) => {
        console.error("Error fetching model catalog:", error);
      });
    setIsLoading(false);
  }

  if (!items) {
    return null;
  }

  // Filter models by searchText
  const filteredModels = items.modelCatalog.filter((model) => {
    if (!searchText) return true;
    const lowerSearch = searchText.toLowerCase();
    return Object.keys(model).some((key) => {
      const value = model[key];
      if (value == null) return false;
      return String(value).toLowerCase().includes(lowerSearch);
    });
  });

  const sortedModels = [...filteredModels].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;

    const valueFor = (item) => {
      if (sort.key === "eventTypes") {
        return Array.isArray(item.eventTypes) && item.eventTypes.length > 0
          ? item.eventTypes.join(", ")
          : "";
      }
      if (sort.key === "additionalInfo") {
        return item.additionalInfo ? "View Metadata" : "--";
      }
      return item[sort.key] ?? "";
    };

    return String(valueFor(a)).localeCompare(String(valueFor(b))) * dir;
  });

  // Pagination logic
  const totalModels = sortedModels.length;
  const totalPages = Math.max(1, Math.ceil(totalModels / pageSize));
  const page = Math.min(currentPage, totalPages);
  const start = totalModels === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalModels);
  const paginatedModels = sortedModels.slice(
    (page - 1) * pageSize,
    page * pageSize
  );
  const hasNoResults =
    !!items && items.modelCatalog.length > 0 && paginatedModels.length === 0;

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  async function handlePageSizeChange(newSize) {
    setPageSize(newSize);
    setCurrentPage(1);
    setIsLoading(true, "Updating Items Per Page...");
    const response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ itemsPerPageModelCatalog: newSize }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        itemsPerPageModelCatalog: newSize,
      },
    }));
    setIsLoading(false);
  }

  const isEmpty = !items || items.modelCatalog.length === 0;

  return (
    <>
      {items && (
        <div className="pgrid-page pgrid-page--model-catalog">
          <div className="pgrid-header">
            <div>
              <h1 className="pgrid-title">
                Model Catalog
                <Tooltip
                  content="Browse and manage reusable base models for training workflows."
                  relationship="label"
                >
                  <span>
                    <FluentIcon name="Info" className="pgrid-title-info" />
                  </span>
                </Tooltip>
              </h1>
              <div className="pgrid-subtitle">
                Browse and manage reusable base models for training workflows.
              </div>
            </div>
          </div>

          {!isEmpty && (
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
              <div className="pgrid-toolbar-spacer" />
            </div>
          )}

          {isEmpty ? (
            <div className="pgrid-empty">
              <FluentIcon name="ProductCatalog" style={{ fontSize: 32 }} />
              <div>No models in catalog yet.</div>
            </div>
          ) : (
            <>
              <div className="pgrid-table-wrap">
                {hasNoResults ? (
                  <NoResultsMessage
                    title="No models found"
                    fallbackMessage="No models match your filters."
                    searchText={searchText}
                    onClear={() => {
                      setSearchText("");
                      setCurrentPage(1);
                    }}
                  />
                ) : (
                  <table className="pgrid-table">
                    <thead>
                      <tr>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("baseModelName")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("baseModelName");
                              }
                            }}
                          >
                            Base Model Name
                            {sort.key === "baseModelName" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("description")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("description");
                              }
                            }}
                          >
                            Description
                            {sort.key === "description" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("imagerySource")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("imagerySource");
                              }
                            }}
                          >
                            Source
                            {sort.key === "imagerySource" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("eventTypes")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("eventTypes");
                              }
                            }}
                          >
                            Event Type
                            {sort.key === "eventTypes" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("cataloguedDate")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("cataloguedDate");
                              }
                            }}
                          >
                            Catalogued Date
                            {sort.key === "cataloguedDate" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("cataloguedByUser")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("cataloguedByUser");
                              }
                            }}
                          >
                            Catalogued By
                            {sort.key === "cataloguedByUser" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th>
                          <span
                            className="pgrid-th-inner pgrid-th-sortable"
                            onClick={() => toggleSort("additionalInfo")}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                toggleSort("additionalInfo");
                              }
                            }}
                          >
                            Metadata
                            {sort.key === "additionalInfo" && (
                              <FluentIcon
                                name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                                className="pgrid-sort-icon"
                              />
                            )}
                          </span>
                        </th>
                        <th className="pgrid-th-actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedModels.map((item, index) => (
                        <ModelCatalogRow
                          item={item}
                          index={(page - 1) * pageSize + index}
                          key={item.modelId}
                          setModalComponent={setModalComponent}
                          fetchModels={initComponent}
                        />
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="pgrid-footer">
                <div>
                  Showing {start}-{end} of {totalModels}
                </div>
                <div className="pgrid-footer-pagination">
                  <button
                    type="button"
                    className="pgrid-page-btn"
                    disabled={page <= 1}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  >
                    <FluentIcon name="ChevronLeft" />
                    Previous
                  </button>
                  <div>
                    Page {page} of {totalPages}
                  </div>
                  <button
                    type="button"
                    className="pgrid-page-btn"
                    disabled={page >= totalPages}
                    onClick={() =>
                      setCurrentPage((p) => Math.min(totalPages, p + 1))
                    }
                  >
                    Next
                    <FluentIcon name="ChevronRight" />
                  </button>
                </div>
                <div className="pgrid-footer-rows">
                  <span>Rows per page:</span>
                  <Dropdown
                    className="pgrid-rows-dropdown"
                    value={String(pageSize)}
                    selectedOptions={[String(pageSize)]}
                    onOptionSelect={(_, data) => {
                      const selected = Number(data.optionValue);
                      if (!Number.isNaN(selected) && selected > 0) {
                        handlePageSizeChange(selected);
                      }
                    }}
                  >
                    {PAGE_SIZE_OPTIONS.map((size) => (
                      <Option key={size} value={String(size)}>
                        {size}
                      </Option>
                    ))}
                  </Dropdown>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {modalComponent}
    </>
  );
};

export default ModelCatalog;
