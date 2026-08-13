import { useContext, useDeferredValue, useEffect, useRef, useState } from "react";
import {
  Dropdown,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
} from "@fluentui/react-components";

import { AppContext } from "../AppContext";
import { apiGet } from "../util/api";
import { FluentIcon } from "../util/icons";
import { isPublishingStatusActive } from "../util/publishing";
import NoResultsMessage from "./NoResultsMessage";
import PublishedDatasetRow from "./PublishedDatasetRow";


const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];
const STATUS_OPTIONS = [
  "PENDING",
  "IN_PROGRESS",
  "PUBLISHED",
  "FAILED",
  "UNPUBLISH_PENDING",
  "UNPUBLISHING",
  "UNPUBLISH_FAILED",
];

const PublishedDatasets = () => {
  const { setIsLoading } = useContext(AppContext);
  const [items, setItems] = useState(null);
  const [totalItems, setTotalItems] = useState(0);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const deferredSearchText = useDeferredValue(searchText);
  const normalizedSearchText = deferredSearchText.trim();
  const searchReady =
    normalizedSearchText.length === 0 || normalizedSearchText.length >= 3;
  const [targetFilter, setTargetFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sort, setSort] = useState({ key: "publishedDate", dir: "desc" });
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  async function fetchDatasets(showLoading = false) {
    if (showLoading) setIsLoading(true, "Loading published datasets...");
    try {
      const query = new URLSearchParams({
        page: String(currentPage),
        pageSize: String(pageSize),
        sortKey: sort.key,
        sortDirection: sort.dir,
      });
      if (targetFilter !== "all") query.set("target", targetFilter);
      if (statusFilter !== "all") query.set("status", statusFilter);
      if (normalizedSearchText) query.set("search", normalizedSearchText);
      const response = await apiGet(`GetPublishedDatasets?${query}`);
      const nextItems = response.publishedDatasets || [];
      const nextTotal = response.pagination?.totalCount ?? nextItems.length;
      setItems(nextItems);
      setTotalItems(nextTotal);
      const nextTotalPages = Math.max(1, Math.ceil(nextTotal / pageSize));
      if (currentPage > nextTotalPages) setCurrentPage(nextTotalPages);
      setError("");
    } catch (fetchError) {
      setError(fetchError.message || "Unable to load published datasets.");
    } finally {
      if (showLoading) setIsLoading(false);
    }
  }

  useEffect(() => {
    if (!searchReady) return;
    // State updates occur after the awaited API response, not synchronously.
    // Show the full-page loading overlay only on the first load (items === null,
    // catalog pattern); later filter/search/sort/page changes refetch silently
    // so the overlay doesn't flash on every keystroke.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchDatasets(items === null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, pageSize, targetFilter, statusFilter, normalizedSearchText, searchReady, sort]);

  const hasActiveItems = (items || []).some((item) =>
    isPublishingStatusActive(item.status),
  );

  // Keep a ref to the latest fetchDatasets so the polling interval always uses
  // the current page/filters/search/sort instead of the values captured when
  // polling first started (which would overwrite fresh results with a stale
  // query).
  const fetchDatasetsRef = useRef(fetchDatasets);
  fetchDatasetsRef.current = fetchDatasets;

  useEffect(() => {
    if (!hasActiveItems || !searchReady) return undefined;
    const interval = window.setInterval(
      () => fetchDatasetsRef.current(false),
      5000,
    );
    return () => window.clearInterval(interval);
  }, [hasActiveItems, searchReady]);

  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const page = Math.min(currentPage, totalPages);
  const start = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalItems);
  const paginated = items || [];
  const hasActiveFilters =
    !!normalizedSearchText || targetFilter !== "all" || statusFilter !== "all";
  const isEmpty = items !== null && totalItems === 0 && !hasActiveFilters;
  const noResults = items !== null && totalItems === 0 && hasActiveFilters;

  function toggleSort(key) {
    setCurrentPage(1);
    setSort((previous) =>
      previous.key === key
        ? { key, dir: previous.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  function sortHeader(key, label) {
    return (
      <span
        className="pgrid-th-inner pgrid-th-sortable"
        onClick={() => toggleSort(key)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") toggleSort(key);
        }}
        role="button"
        tabIndex={0}
      >
        {label}
        {sort.key === key && (
          <FluentIcon
            name={sort.dir === "asc" ? "SortUp" : "SortDown"}
            className="pgrid-sort-icon"
          />
        )}
      </span>
    );
  }

  if (items === null && !error) return null;

  return (
    <div className="pgrid-page pgrid-page--model-catalog pgrid-page--published-datasets">
      <div className="pgrid-header">
        <div>
          <h1 className="pgrid-title">Published Datasets</h1>
          <div className="pgrid-subtitle">
            Curated outputs published from completed HASTE results.
          </div>
        </div>
      </div>

      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}

      {!isEmpty && items && (
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
          <Dropdown
            aria-label="Filter by target"
            value={targetFilter === "all" ? "All targets" : targetFilter === "local" ? "Local" : "Planetary Computer"}
            selectedOptions={[targetFilter]}
            onOptionSelect={(_, data) => {
              setTargetFilter(data.optionValue || "all");
              setCurrentPage(1);
            }}
          >
            <Option value="all">All targets</Option>
            <Option value="local">Local</Option>
            <Option value="planetary_computer">Planetary Computer</Option>
          </Dropdown>
          <Dropdown
            aria-label="Filter by status"
            value={statusFilter === "all" ? "All statuses" : statusFilter}
            selectedOptions={[statusFilter]}
            onOptionSelect={(_, data) => {
              setStatusFilter(data.optionValue || "all");
              setCurrentPage(1);
            }}
          >
            <Option value="all">All statuses</Option>
            {STATUS_OPTIONS.map((status) => (
              <Option key={status} value={status}>
                {status.replaceAll("_", " ")}
              </Option>
            ))}
          </Dropdown>
          <div className="pgrid-toolbar-spacer" />
        </div>
      )}

      {isEmpty ? (
        <div className="pgrid-empty">
          <FluentIcon name="Database" style={{ fontSize: 32 }} />
          <div>No published datasets yet.</div>
        </div>
      ) : (
        items && (
          <>
            <div className="pgrid-table-wrap">
              {noResults ? (
                <NoResultsMessage
                  title="No datasets found"
                  fallbackMessage="No published datasets match your filters."
                  searchText={searchText}
                  onClear={() => {
                    setSearchText("");
                    setTargetFilter("all");
                    setStatusFilter("all");
                    setCurrentPage(1);
                  }}
                />
              ) : (
                <table className="pgrid-table">
                  <thead>
                    <tr>
                      <th>{sortHeader("name", "Name")}</th>
                      <th>{sortHeader("projectName", "Project / Layer")}</th>
                      <th>{sortHeader("target", "Target")}</th>
                      <th>{sortHeader("status", "Status")}</th>
                      <th>{sortHeader("publishedByUser", "Published by")}</th>
                      <th>{sortHeader("publishedDate", "Published date")}</th>
                      <th className="pgrid-th-actions" aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.map((item, index) => (
                      <PublishedDatasetRow
                        key={item.datasetId}
                        item={item}
                        index={(page - 1) * pageSize + index}
                        onRefresh={() => fetchDatasets(false)}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="pgrid-footer">
              <div>
                Showing {start}-{end} of {totalItems}
              </div>
              <div className="pgrid-footer-pagination">
                <button
                  type="button"
                  className="pgrid-page-btn"
                  disabled={page <= 1}
                  onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
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
                  onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                >
                  Next
                  <FluentIcon name="ChevronRight" />
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
                    const selected = Number(data.optionValue);
                    if (selected > 0) {
                      setPageSize(selected);
                      setCurrentPage(1);
                    }
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
        )
      )}
    </div>
  );
};

export default PublishedDatasets;