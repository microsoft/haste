// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { useState, useEffect, useContext } from "react";
import ModelCatalogHeader from "./ProjectManagement/ModelCatalogHeader";
import NoResults from "./ProjectManagement/NoResults";
import SectionHeader from "./Section/SectionHeader";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import { apiGet } from "../util/api";
import PaginationControls from "./OtherComponents/PaginationControls";
import { AppContext } from "../AppContext";
import ModelCatalogRow from "./ProjectManagement/ModelCatalogRow";

const ModelCatalog = () => {
  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams } = useContext(AppContext);
  const [modalComponent, setModalComponent] = useState();
  const [items, setItems] = useState(null);
  const [moreInfoVisibleId, setMoreInfoVisibleId] = useState(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Search state
  const [searchText, setSearchText] = useState("");

  useEffect(() => {
    setCurrentPage(1);
  }, [appParams.userSettings.itemsPerPage]);

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

  useEffect(() => {
    function handleResize() {
      if (appParams.bootstrapBreakpoint >= 3) {
        setMoreInfoVisibleId(null);
      }
    }
    window.addEventListener("resize", handleResize);
    handleResize();
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [appParams.bootstrapBreakpoint]);

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

  // Pagination logic
  const totalModels = filteredModels.length;
  const PAGE_SIZE = appParams.userSettings.itemsPerPage ?? 10;
  const totalPages = Math.ceil(totalModels / PAGE_SIZE);
  const paginatedModels = filteredModels.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const sectionHeaderProperties = {
    iconName: "ProductCatalog",
    path: [{ name: "Model Catalog", link: "" }],
    links: items.modelCatalog.length > 0
      ? []
      : [],
    filter: true,
  };

  return (
    <>
      {items && (
        <div className="d-flex flex-column w-100 mb-5">
          <SectionHeader properties={sectionHeaderProperties} searchText={searchText} setSearchText={setSearchText} setCurrentPage={setCurrentPage} />
          <div className="container p-md-0">
            <div className="row m-0 p-0 pt-5">
              <div className="col-12" style={{ overflowX: "auto" }}>
                <table className="col-12 dashboard-table">
                  <ModelCatalogHeader />
                  <tbody>
                    {paginatedModels.map((item, index) => (
                      <ModelCatalogRow
                        item={item}
                        index={index}
                        key={item.modelId}
                        setModalComponent={setModalComponent}
                        fetchModels={initComponent}
                        moreInfoVisibleId={moreInfoVisibleId}
                        setMoreInfoVisibleId={setMoreInfoVisibleId}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <NoResults items={filteredModels} text={"No models found"} />


            {/* Pagination Controls */}
            <PaginationControls totalPages={totalPages} currentPage={currentPage} setCurrentPage={setCurrentPage} />
          </div>
        </div>
      )}

      {modalComponent}
    </>
  );
};

export default ModelCatalog;
