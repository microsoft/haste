// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { PrimaryButton, Text } from "@fluentui/react";

import { useState, useEffect, useContext } from "react";
import { apiGet } from "../util/api";
import SourceTypeRow from "./ProjectManagement/SourceTypeRow";
import SectionHeader from "./Section/SectionHeader";

import { AppContext } from "../AppContext";

import CreateEditSourceTypeModal from "./CreateEditSourceTypeModal";

const AdminSourceTypes = () => {

  const [componentState, setComponentState] = useState(null);
  const [modalComponent, setModalComponent] = useState(null);
  const { setIsLoading, appParams } = useContext(AppContext);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);


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

  return (
    <>
      <div className="d-flex flex-column w-100">
        <SectionHeader properties={sectionHeaderProperties} />

        <div className="container p-0">
          <div className="row m-0 mt-5 p-0">
            <div className="col-12 d-flex justify-content-startr">
              <PrimaryButton
                text="Add Source Type"
                onClick={() =>
                  setModalComponent(
                    <CreateEditSourceTypeModal
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
                    <th className="pb-3 pe-4">
                      <Text className="fw-semibold">Name</Text>
                    </th>
                    <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
                      <Text className="fw-semibold">Base URL</Text>
                    </th>
                    <th className="pb-3 pe-4">
                      <Text className="fw-semibold custom-text-no-wrap d-none d-xl-table-cell">Creation Date</Text>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {componentState.map((item) => (
                    <SourceTypeRow
                      item={item}
                      key={item.key}
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
