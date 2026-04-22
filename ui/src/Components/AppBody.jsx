// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Route, Routes, useLocation } from "react-router-dom";
import { useContext, useEffect } from "react";

import Loading from "./OtherComponents/Loading";
import Error404 from "./Error404";
import Project from "./Project";
import Projects from "./Projects";
import ImageLayer from "./ImageLayer";
import Home from "./Home";
import LabelingTool from "./LabelingTool/LabelingTool";
import Visualizer from "./Visualizer/Visualizer";
import ModelCatalog from "./ModelCatalog";

import AdminUsers from "./AdminUsers";
import AdminSourceTypes from "./AdminSourceTypes";
import AdminLabelingTool from "./AdminLabelingTool";
import CreateEditImageLayerForm from "./CreateEditImageLayerForm";
import HelpDocs from "./HelpDocs";
import { apiValidateUser, apiLogout } from "../util/api";
import PropType from "prop-types";

import { AppContext } from "../AppContext";

const AppBody = ({ setModalComponent }) => {
  AppBody.propTypes = {
    setModalComponent: PropType.func.isRequired,
  };

  const { appParams } = useContext(AppContext);

  return (
    <div className="d-flex flex-grow-1 justify-content-center">
      {appParams.isLoading && <Loading />}
      <Routes>
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
      </Routes>
    </div>
  );
};

export default AppBody;
