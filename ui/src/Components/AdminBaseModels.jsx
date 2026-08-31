// Components
import { Text } from "@fluentui/react-components";

import { useState, useEffect, useContext } from "react";

import { apiGet } from "../util/api";
import { FluentIcon } from "../util/icons";

import BaseModelRow from "./ProjectManagement/BaseModelRow";
import SectionHeader from "./Section/SectionHeader";

import { AppContext } from "../AppContext";

const AdminBaseModels = () => {

  const [componentState, setComponentState] = useState(null);
  const { setIsLoading } = useContext(AppContext);
  const [sort, setSort] = useState({ key: "creationDate", dir: "desc" });

  function toggleSort(key) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  useEffect(() => {
    async function fetchBaseModels() {
      setIsLoading(true);
      await apiGet("GetAdminSettings")
        .then((response) => {
          setComponentState(response.baseModels);
        })
        .catch((error) => {
          console.error("Error fetching base models:", error);
        });
      setIsLoading(false);
    }

    fetchBaseModels();
  
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  /* Section Header Properties */

  const sectionHeaderProperties = {
    iconName: "UserEvent",
    path: [{ name: "Base Model Management", link: "" }],
    links: [
      {
        name: "Source Types",
        link: "/admin-source-types",
      },
      {
        name: "Base Models",
        link: "/admin-base-models",
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

  if(componentState === null) {
    return null;
  }

  const sortedBaseModels = [...componentState].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;
    return String(a[sort.key] ?? "").localeCompare(String(b[sort.key] ?? "")) * dir;
  });

  return (
    <>
      <div className="d-flex flex-column w-100">
        <SectionHeader properties={sectionHeaderProperties} />

        <div className="container p-0">
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
                    <th className="pb-3 pe-4">
                      <span
                        className="pgrid-th-inner pgrid-th-sortable"
                        onClick={() => toggleSort("sourceURL")}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            toggleSort("sourceURL");
                          }
                        }}
                      >
                        <Text className="fw-semibold">Source URL</Text>
                        {sort.key === "sourceURL" && (
                          <FluentIcon
                            name={sort.dir === "asc" ? "SortUp" : "SortDown"}
                            className="pgrid-sort-icon"
                          />
                        )}
                      </span>
                    </th>
                    <th className="pb-3 pe-4">
                      <span
                        className="pgrid-th-inner pgrid-th-sortable"
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
                    <th className="pb-3 pe-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedBaseModels.map((item, index) => (
                    <BaseModelRow
                      item={item}
                      key={item.baseModelId || item.name || index}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AdminBaseModels;
