// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Route, Routes } from "react-router-dom";
import { lazy, Suspense, useContext } from "react";

import Loading from "./OtherComponents/Loading";
import PropType from "prop-types";

import { AppContext } from "../AppContext";
import { createMapRoute, RouteLoading } from "./MapRoute";

const AdminLabelingTool = lazy(() => import("./AdminLabelingTool"));
const AdminSourceTypes = lazy(() => import("./AdminSourceTypes"));
const AdminUsers = lazy(() => import("./AdminUsers"));
const BuildingValidation = createMapRoute(
  () => import("./BuildingValidation/BuildingValidation")
);
const CreateEditImageLayerForm = lazy(
  () => import("./CreateEditImageLayerForm")
);
const Error404 = lazy(() => import("./Error404"));
const HelpDocs = lazy(() => import("./HelpDocs"));
const Home = lazy(() => import("./Home"));
const ImageLayer = lazy(() => import("./ImageLayer"));
const InteractiveLabeler = createMapRoute(
  () => import("./InteractiveLabeler/InteractiveLabeler")
);
const LabelingTool = createMapRoute(
  () => import("./LabelingTool/LabelingTool")
);
const ModelCatalog = lazy(() => import("./ModelCatalog"));
const Project = lazy(() => import("./Project"));
const Projects = lazy(() => import("./Projects"));
const PublishedDatasets = lazy(() => import("./PublishedDatasets"));
const Visualizer = createMapRoute(() => import("./Visualizer/Visualizer"));

const AppBody = ({ setModalComponent }) => {
  const { appParams } = useContext(AppContext);
  const routesReady =
    appParams.userRoles !== null && appParams.publishingEnabled !== null;

  return (
    <div className="app-body-shell d-flex flex-grow-1 justify-content-center">
      {appParams.isLoading && <Loading />}
      {routesReady && <Suspense fallback={<RouteLoading />}><Routes>
        {appParams.userRoles !== null && appParams.publishingEnabled && (
          <Route path="/published-datasets" element={<PublishedDatasets />} />
        )}
        {appParams.userRoles !== null &&
          (appParams.userRoles.includes("administrators") ||
            appParams.userRoles.includes("contributors")) && (
            <>
              <Route path="/" element={<Home />} />

              <Route path="/projects" element={<Projects />} />
              <Route path="/project/:projectId" element={<Project setModalComponent={setModalComponent} />} />
              <Route path="/project/:projectId/:imageLayerId" element={<Project setModalComponent={setModalComponent} />} />
              <Route
                path="/project/:projectId/imageLayer/:imageLayerId"
                element={<ImageLayer />}
              />
              <Route
                path="/create-imageLayer/:projectId"
                element={<CreateEditImageLayerForm />}
              />
              <Route
                path="/edit-imageLayer/:projectId/:imageLayerId"
                element={<CreateEditImageLayerForm />}
              />
              <Route
                path="/labeling-tool/:projectId/:imageLayerId"
                element={<LabelingTool setModalComponent={setModalComponent} />}
              />
              <Route
                path="/validation/:projectId/:imageLayerId"
                element={<BuildingValidation />}
              />
              <Route
                path="/interactive-label/:projectId/:imageLayerId/:modelId"
                element={<InteractiveLabeler />}
              />
              <Route
                path="/visualizer/:projectId/:imageLayerId/:modelId"
                element={<Visualizer setModalComponent={setModalComponent} />}
              />
              <Route
                path="/help-docs/*"
                element={<HelpDocs setModalComponent={setModalComponent} />}
              />
              <Route path="*" element={<Error404 />} />
            </>
          )}

        {/* ADMIN */}
        {appParams.userRoles !== null &&
          appParams.userRoles.includes("administrators") && (
            <>
              <Route
                path="/model-catalog"
                element={<ModelCatalog setModalComponent={setModalComponent} />}
              />
              <Route path="/admin-users" element={<AdminUsers setModalComponent={setModalComponent} />} />
              <Route
                path="/admin-source-types"
                element={<AdminSourceTypes />}
              />
              <Route
                path="/admin-labeling-tool"
                element={<AdminLabelingTool />}
              />
            </>
          )}

        <Route path="*" element={<Error404 />} />
      </Routes></Suspense>}
    </div>
  );
};

AppBody.propTypes = {
  setModalComponent: PropType.func.isRequired,
};

export default AppBody;
