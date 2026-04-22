// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import PropTypes from "prop-types";
import { Text, Link, TooltipHost } from "@fluentui/react";
import ProjectInsightsBubble from "./ProjectInsightsBuble";
import { useNavigate } from "react-router-dom";
import { limitTextLength } from "../../util/conversion";

const OpenProject = ({ openProject, index }) => {
  OpenProject.propTypes = {
    openProject: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
  };

  const navigate = useNavigate();

  return (
    <Link
      onClick={() => navigate(`/project/${openProject.projectId}`)}
      style={{ textDecoration: "none" }}
      className="w-100"
    >
      <div
        key={openProject.id}
        className="col-12 d-flex mt-4 align-items-lg-center flex-column flex-md-row"
      >
        <div className="col pe-md-4 pe-lg-5">
          <h6 className="mb-2 custom-text-color">
            <TooltipHost
              content={openProject.name}
              delay={2}
            >
            {limitTextLength(openProject.name,30,100)}
            </TooltipHost>
          </h6>
          <Text
            variant="mediumPlus"
            className="home-project-description mb-3 mb-md-0"
          >
            <TooltipHost
              content={openProject.description}
              delay={2}
            >
            {limitTextLength(openProject.description,200,500)}
            </TooltipHost>
          </Text>
        </div>
        <div className="col-auto mt-2 md-lg-0 d-none d-lg-block">
          <ProjectInsightsBubble
            label={"Image Layers"}
            quantity={openProject.imageLayerCount}
          />
        </div>
        <div className="col-auto mt-2 md-lg-0 d-none d-lg-block">
          <ProjectInsightsBubble
            label={"Models"}
            quantity={openProject.modelsCount}
          />
        </div>
        <div className="col-auto mt-2 md-lg-0 d-none d-lg-block">
          <ProjectInsightsBubble
            label={"Labels"}
            quantity={openProject.labelsCount}
          />
        </div>
      </div>
      {index <= 1 ? (
        <hr className="w-100 dashboard-hr" />
      ) : (
        <div className="w-100 pb-3"></div>
      )}
    </Link>
  );
};

export default OpenProject;
