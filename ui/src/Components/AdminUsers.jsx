// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { PrimaryButton, Text, IconButton } from "@fluentui/react";
import { useState, useEffect, useContext } from "react";
import { apiGet } from "../util/api";
import UserRow from "./ProjectManagement/UserRow";
import SectionHeader from "./Section/SectionHeader";
import { AppContext } from "../AppContext";
import CreateEditUserModal from "./CreateEditUserModal";
import PaginationControls from "./OtherComponents/PaginationControls";
import PropTypes from "prop-types";

const AdminUsers = ({ setModalComponent }) => {
  AdminUsers.propTypes = {
    setModalComponent: PropTypes.func.isRequired,
  };

  const [componentState, setComponentState] = useState(null);
  const { setIsLoading, appParams } = useContext(AppContext);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Search/filter state
  const [searchText, setSearchText] = useState("");

  useEffect(() => {
    setCurrentPage(1);
  }, [appParams.userSettings.itemsPerPage]);

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

  // Section Header Properties
  const sectionHeaderProperties = {
    iconName: "UserEvent",
    path: [{ name: "User Management", link: "" }],
    links: [
      {
        name: "Users",
        link: "/admin-users",
      }
    ],
    filter: true
  };

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
  const totalUsers = filteredUsers.length;
  const totalPages = Math.ceil(totalUsers / (appParams.userSettings.itemsPerPage ?? 10));
  const startIdx = (currentPage - 1) * (appParams.userSettings.itemsPerPage ?? 10);
  const endIdx = startIdx + (appParams.userSettings.itemsPerPage ?? 10);
  const currentUsers = filteredUsers.slice(startIdx, endIdx);

  return (
    <>
      <div className="d-flex flex-column w-100 mb-5">
        <SectionHeader
          properties={sectionHeaderProperties}
          searchText={searchText}
          setSearchText={(text) => {
            setSearchText(text);
            setCurrentPage(1); // Reset to first page on search
          }}
          setCurrentPage={setCurrentPage}
        />

        <div className="container p-0">
          <div className="row m-0 mt-5 p-0">
            <div className="col-12 d-flex justify-content-startr">
              <PrimaryButton
                text="Add User"
                onClick={() =>
                  setModalComponent(
                    <CreateEditUserModal
                      onClose={() => setModalComponent(null)}
                    />
                  )
                }
              />
            </div>
          </div>
          <div className="row m-0 p-0 pt-5">
            <div className="col-12">
              <table className="col-12 dashboard-table">
                <thead>
                  <tr>
                    <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
                      <Text className="fw-semibold">Name</Text>
                    </th>
                    <th className="pb-3 pe-4">
                      <Text className="fw-semibold">E-mail</Text>
                    </th>
                    <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
                      <Text className="fw-semibold">User Roles</Text>
                    </th>
                    <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
                      <Text className="fw-semibold">Status</Text>
                    </th>
                    <th className="pb-3 pe-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {currentUsers.map((item, index) => (
                    <UserRow
                      key={item.id || index}
                      item={item}
                      index={startIdx + index}
                      setModalComponent={setModalComponent}
                      moreInfoVisibleId={moreInfoVisibleId}
                      setMoreInfoVisibleId={setMoreInfoVisibleId}
                    />
                  ))}
                </tbody>
              </table>

              {/* Pagination Controls */}
              <PaginationControls totalPages={totalPages} currentPage={currentPage} setCurrentPage={setCurrentPage} />

            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AdminUsers;
