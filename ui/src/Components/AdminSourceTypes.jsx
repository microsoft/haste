// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Button, Text } from "@fluentui/react-components";

import { useState, useEffect, useContext } from "react";
import { apiGet } from "../util/api";
import SourceTypeRow from "./ProjectManagement/SourceTypeRow";
import SectionHeader from "./Section/SectionHeader";
import { FluentIcon } from "../util/icons";

import { AppContext } from "../AppContext";

import CreateEditSourceTypeModal from "./CreateEditSourceTypeModal";

const AdminSourceTypes = () => {

  const [componentState, setComponentState] = useState(null);
  const [modalComponent, setModalComponent] = useState(null);
  const { setIsLoading, appParams } = useContext(AppContext);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);
  const [sort, setSort] = useState({ key: "creationDate", dir: "desc" });

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }


  useEffect(() => {

    async function fetchSourceTypes() {
      setIsLoading(true);
      await apiGet("GetAdminSettings")
        .then((response) => {
          setComponentState(response.sourceTypes);
        })
        .catch((error) => {
          console.error("Error fetching users:", error);
        });
      setIsLoading(false);
    }

    fetchSourceTypes();

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

  /* Section Header Properties */

  const sectionHeaderProperties = {
    iconName: "UserEvent",
    path: [{ name: "Source Type Management", link: "" }],
    links: [
      {
        name: "Users",
        link: "/admin-users",
      },
      {
        name: "Source Types",
        link: "/admin-source-types",
      },
      {
        name: "Labeling Tool",
        link: "/admin-labeling-tool",
      },
    ],
    filter: false,
    filterText: "",
    filterButtonText: "",
    filterPlaceholder: "",
  };

  if (componentState === null) {
    return null;
  }

  const sortedSourceTypes = [...componentState].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;
    return String(a[sort.key] ?? "").localeCompare(String(b[sort.key] ?? "")) * dir;
  });

  return (
    <>
      <div className="d-flex flex-column w-100">
        <SectionHeader properties={sectionHeaderProperties} />

        <div className="container p-0">
          <div className="row m-0 mt-5 p-0">
            <div className="col-12 d-flex justify-content-startr">
              <Button
                appearance="primary"
                icon={<FluentIcon name="FabricNewFolder" />}
                onClick={() =>
                  setModalComponent(
                    <CreateEditSourceTypeModal
                      onClose={() => setModalComponent(null)}
                    />
                  )
                }
              >
                Add Source Type
              </Button>
            </div>
          </div>
          <div className="row m-0 p-0 pt-5">
            <div className="col-12">
              <table className="col-12 dashboard-table">
                <thead>
                  <tr>
                    <th className="pb-3 pe-4">
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
                        <Text className="fw-semibold">Name</Text>
                        {sort.key === "name" && (
                          <FluentIcon
                            name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                            className="pgrid-sort-icon"
                          />
                        )}
                      </span>
                    </th>
                    <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
                      <span
                        className="pgrid-th-inner pgrid-th-sortable"
                        onClick={() => toggleSort("baseURL")}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            toggleSort("baseURL");
                          }
                        }}
                      >
                        <Text className="fw-semibold">Base URL</Text>
                        {sort.key === "baseURL" && (
                          <FluentIcon
                            name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                            className="pgrid-sort-icon"
                          />
                        )}
                      </span>
                    </th>
                    <th className="pb-3 pe-4">
                      <span
                        className="pgrid-th-inner pgrid-th-sortable custom-text-no-wrap d-none d-xl-inline-flex"
                        onClick={() => toggleSort("creationDate")}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            toggleSort("creationDate");
                          }
                        }}
                      >
                        <Text className="fw-semibold">Creation Date</Text>
                        {sort.key === "creationDate" && (
                          <FluentIcon
                            name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                            className="pgrid-sort-icon"
                          />
                        )}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedSourceTypes.map((item, index) => (
                    <SourceTypeRow
                      item={item}
                      key={item.sourceTypeId || item.name || index}
                      moreInfoVisibleId={moreInfoVisibleId}
                      setMoreInfoVisibleId={setMoreInfoVisibleId}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      {modalComponent}
    </>
  );
};

export default AdminSourceTypes;
