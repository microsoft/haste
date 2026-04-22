// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import PropTypes from "prop-types";

const ProjectInsightsBubble = ({ label, quantity }) => {
  ProjectInsightsBubble.propTypes = {
    label: PropTypes.string.isRequired,
    quantity: PropTypes.number.isRequired,
  };

  return (
    <div className="d-flex flex-column fw-semibold home-project-insights-bubble ps-2">
      <div className="home-project-insights-bubble-label">{label}</div>
      <div className="w-100 d-flex text-align-end align-items-center  home-project-insights-bubble-quantity ">
          {quantity}
        </div>
    </div>
  );
};

export default ProjectInsightsBubble;
