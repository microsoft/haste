// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react-components";

import React from "react";

const ProjectHeader = () => {
  return (
    <React.Fragment>
      <thead id="projectsTable">
        <tr>
          <th className="pb-3 pe-4 custom-text-no-wrap">
            <Text className="fw-semibold">Name</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-lg-table-cell">
            <Text className="fw-semibold">Description</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Layer Count</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Creation Date</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap"></th>
        </tr>
      </thead>
    </React.Fragment>
  );
};

export default ProjectHeader;
