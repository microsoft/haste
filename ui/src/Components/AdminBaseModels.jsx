// Components
import { PrimaryButton, Text } from "@fluentui/react";

import { useState, useEffect, useContext } from "react";

import { apiGet } from "../util/api";

import BaseModelRow from "./ProjectManagement/BaseModelRow";
import SectionHeader from "./Section/SectionHeader";

import { AppContext } from "../AppContext";

import CreateEditBaseModelModal from "./CreateEditBaseModelModal";

const AdminBaseModels = () => {

  const [componentState, setComponentState] = useState(null);
  const [modalComponent, setModalComponent] = useState(null);
  const { setIsLoading } = useContext(AppContext);

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

  return (
    <>
      <div className="d-flex flex-column w-100">
        <SectionHeader properties={sectionHeaderProperties} />

        <div className="container p-0">
          <div className="row m-0 mt-5 p-0">
            <div className="col-12 d-flex justify-content-startr">
              <PrimaryButton
                text="Add Base Model"
                onClick={() =>
                  setModalComponent(
                    <CreateEditBaseModelModal
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
                    <th className="pb-3 pe-4">
                      <Text className="fw-semibold">Source URL</Text>
                    </th>
                    <th className="pb-3 pe-4">
                      <Text className="fw-semibold">Creation Date</Text>
                    </th>                    
                    <th className="pb-3 pe-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {componentState.map((item) => (
                    <BaseModelRow item={item} key={item.key} />
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

export default AdminBaseModels;
