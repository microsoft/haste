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
import PropTypes from "prop-types";

const PAGE_SIZE_OPTIONS = [5, 8, 10, 20, 50];

const AdminUsers = ({ setModalComponent }) => {
  AdminUsers.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
  };

  const [componentState, setComponentState] = useState(null);
  const { setIsLoading, appParams, setAppParams } = useContext(AppContext);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(
    appParams.userSettings.itemsPerPage ?? 10
  );

  // Search/filter state
  const [searchText, setSearchText] = useState("");

  // Update the local page size and persist it to the global user setting so
  // the choice is reflected everywhere (mirrors the Settings modal).
  async function handlePageSizeChange(newSize) {
    setPageSize(newSize);
    setCurrentPage(1);
    setIsLoading(true, "Updating Items Per Page...");
    const response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ itemsPerPage: newSize }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        itemsPerPage: newSize,
      },
    }));
    setIsLoading(false);
  }

  useEffect(() => {
    async function fetchUsers() {
      await apiGet("GetUsers")
        .then((response) => {
          setComponentState(response);
        })
        .catch((error) => {
          console.error("Error fetching users:", error);
        });
      setIsLoading(false);
    }

    fetchUsers();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function handleResize() {
      if (appParams.bootstrapBreakpoint >= 3) {
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

  // Pagination logic
  const total = filteredUsers.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startIdx = (currentPage - 1) * pageSize;
  const endIdx = startIdx + pageSize;
  const currentUsers = filteredUsers.slice(startIdx, endIdx);
  const start = total === 0 ? 0 : startIdx + 1;
  const end = Math.min(currentPage * pageSize, total);
  const isEmpty = componentState.length === 0;

  const openCreateUser = () =>
    setModalComponent(
      <CreateEditUserModal onClose={() => setModalComponent(null)} />
    );

  return (
    <div className="d-flex flex-column w-100">
      <div className="pgrid-page">
        {/* Header */}
        <div className="pgrid-header">
          <div>
            <h1 className="pgrid-title">
              Users
            </h1>
            <div className="pgrid-subtitle">
              Manage user access, roles, and invitations.
            </div>
          </div>
          {!isEmpty && (
            <Button
              className="pgrid-new-btn"
              appearance="primary"
              icon={<FluentIcon name="Add" />}
              onClick={openCreateUser}
            >
              Add User
            </Button>
          )}
        </div>

        {isEmpty ? (
          <div className="pgrid-empty">
            <FluentIcon name="UserEvent" style={{ fontSize: 32 }} />
            <div>No users yet. Invite your first user to get started.</div>
            <Button
              appearance="primary"
              icon={<FluentIcon name="Add" />}
              onClick={openCreateUser}
            >
              Add User
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
              <table className="pgrid-table">
                <thead>
                  <tr>
                    <th className="d-none d-xl-table-cell">Name</th>
                    <th>E-mail</th>
                    <th className="d-none d-xl-table-cell">User Roles</th>
                    <th className="d-none d-xl-table-cell">Status</th>
                    <th className="pgrid-th-actions" />
                  </tr>
                </thead>
                <tbody>
                  {currentUsers.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        className="pgrid-muted"
                        style={{ textAlign: "center", padding: "32px" }}
                      >
                        No users match your search.
                      </td>
                    </tr>
                  ) : (
                    currentUsers.map((item, index) => (
                      <UserRow
                        key={item.id || index}
                        item={item}
                        index={startIdx + index}
                        setModalComponent={setModalComponent}
                        moreInfoVisibleId={moreInfoVisibleId}
                        setMoreInfoVisibleId={setMoreInfoVisibleId}
                      />
                    ))
                  )}
                </tbody>
              </table>
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
