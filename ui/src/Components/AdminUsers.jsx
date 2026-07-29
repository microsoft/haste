// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Button,
  SearchBox,
  Dropdown,
  Option,
  Tooltip,
} from "@fluentui/react-components";
import { useState, useEffect, useContext } from "react";
import { apiGet } from "../util/api";
import UserRow from "./ProjectManagement/UserRow";
import { FluentIcon } from "../util/icons";
import { AppContext } from "../AppContext";
import { updateUserSettings } from "../AppHelper";
import CreateEditUserModal from "./CreateEditUserModal";
import NoResultsMessage from "./NoResultsMessage";
import PropTypes from "prop-types";

const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];

const AdminUsers = ({ setModalComponent }) => {
  AdminUsers.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
  };

  const [componentState, setComponentState] = useState(null);
  const { setIsLoading, appParams, setAppParams } = useContext(AppContext);
  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(
    appParams.userSettings.itemsPerPage ?? 10
  );

  // Search/filter state
  const [searchText, setSearchText] = useState("");
  const [sort, setSort] = useState({ key: "name", dir: "asc" });

  // Update the local page size and persist it to the global user setting so
  // the choice is reflected everywhere (mirrors the Settings modal).
  async function handlePageSizeChange(newSize) {
    setPageSize(newSize);
    setCurrentPage(1);
    setIsLoading(true, "Updating Items Per Page...");
    try {
      const response = await apiGet("GetUserById?userId=" + appParams.userId);
      await updateUserSettings(response, [{ itemsPerPage: newSize }]);
      setAppParams((prevParams) => ({
        ...prevParams,
        userSettings: {
          ...prevParams.userSettings,
          itemsPerPage: newSize,
        },
      }));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    async function fetchUsers() {
      setIsLoading(true, "Loading...");
      try {
        const response = await apiGet("GetUsers");
        setComponentState(response);
      } catch (error) {
        console.error("Error fetching users:", error);
      } finally {
        setIsLoading(false);
      }
    }

    fetchUsers();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!componentState) {
    return null;
  }

  // Filter users by any field (name, email, roles, status)
  const filteredUsers = componentState.filter((user) => {
    if (!searchText) return true;
    const lowerSearch = searchText.toLowerCase();
    return (
      (user.name && user.name.toLowerCase().includes(lowerSearch)) ||
      (user.email && user.email.toLowerCase().includes(lowerSearch)) ||
      (user.roles && user.roles.join(", ").toLowerCase().includes(lowerSearch)) ||
      (user.status && user.status.toLowerCase().includes(lowerSearch))
    );
  });

  const sortedUsers = [...filteredUsers].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;

    const valueFor = (item) => {
      if (sort.key === "userRoles") {
        return Array.isArray(item.userRoles) ? item.userRoles.join(", ") : "";
      }
      return item[sort.key] ?? "";
    };

    return String(valueFor(a)).localeCompare(String(valueFor(b))) * dir;
  });

  // Pagination logic
  const total = sortedUsers.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startIdx = (currentPage - 1) * pageSize;
  const endIdx = startIdx + pageSize;
  const currentUsers = sortedUsers.slice(startIdx, endIdx);
  const isEmpty = componentState.length === 0;
  const hasSearchNoResults = !isEmpty && currentUsers.length === 0;
  const start = total === 0 ? 0 : startIdx + 1;
  const end = Math.min(currentPage * pageSize, total);

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  const openCreateUser = () =>
    setModalComponent(
      <CreateEditUserModal onClose={() => setModalComponent(null)} />
    );

  return (
    <div className="d-flex flex-column w-100">
      <div className="pgrid-page pgrid-page--users">
        {/* Header */}
        <div className="pgrid-header">
          <div>
            <h1 className="pgrid-title">
              Users
              <Tooltip
                content="Manage user access, roles, and invitations."
                relationship="label"
              >
                <span>
                  <FluentIcon name="Info" className="pgrid-title-info" />
                </span>
              </Tooltip>
            </h1>
            <div className="pgrid-subtitle">
              Manage user access, roles, and invitations.
            </div>
          </div>
          {!isEmpty && (
            <Button
              className="pgrid-new-btn"
              appearance="primary"
              icon={<FluentIcon name="UserEvent" style={{ fontSize: 17 }} />}
              onClick={openCreateUser}
            >
              New User
            </Button>
          )}
        </div>

        {isEmpty ? (
          <div className="pgrid-empty">
            <FluentIcon name="UserEvent" style={{ fontSize: 32 }} />
            <div>No users yet. Invite your first user to get started.</div>
            <Button
              appearance="primary"
              icon={<FluentIcon name="UserEvent" style={{ fontSize: 17 }} />}
              onClick={openCreateUser}
            >
              New User
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
            </div>

            <div className="pgrid-table-wrap">
              {hasSearchNoResults ? (
                <NoResultsMessage
                  title="No users found"
                  fallbackMessage="No users match your filters."
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
                          onClick={() => toggleSort("name")}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              toggleSort("name");
                            }
                          }}
                        >
                          Name
                          {sort.key === "name" && (
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
                          onClick={() => toggleSort("email")}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              toggleSort("email");
                            }
                          }}
                        >
                          E-mail
                          {sort.key === "email" && (
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
                          onClick={() => toggleSort("userRoles")}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              toggleSort("userRoles");
                            }
                          }}
                        >
                          User Roles
                          {sort.key === "userRoles" && (
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
                          onClick={() => toggleSort("status")}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              toggleSort("status");
                            }
                          }}
                        >
                          Status
                          {sort.key === "status" && (
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
                    {currentUsers.map((item, index) => (
                      <UserRow
                        key={item.id || index}
                        item={item}
                        index={startIdx + index}
                        setModalComponent={setModalComponent}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Footer */}
            <div className="pgrid-footer">
              <div>
                Showing {start}–{end} of {total}
              </div>
              <div className="pgrid-footer-pagination">
                <button
                  type="button"
                  className="pgrid-page-btn"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                >
                  <FluentIcon name="ArrowLeft" className="pgrid-page-btn-icon" />
                  Previous
                </button>
                <span className="pgrid-footer-page">
                  Page <b>{currentPage}</b> of {totalPages}
                </span>
                <button
                  type="button"
                  className="pgrid-page-btn"
                  disabled={currentPage >= totalPages}
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
    </div>
  );
};

export default AdminUsers;
