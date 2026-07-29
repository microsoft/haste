// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react-components";

import React from "react";

const ProjectHeader = () => {
  return (
    <React.Fragment>
      <thead id="singleProjectTable">
        <tr>
          <th className="pb-3 pe-4 custom-text-no-wrap" colSpan={2}>
            <Text className="fw-semibold">Image Layer</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Status</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Labeling</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Model Training</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Building Validation</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xxl-table-cell">
            <Text className="fw-semibold">Creator</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xxl-table-cell">
            <Text className="fw-semibold">Creation Date</Text>
          </th>
          <th className="pb-3 d-none d-xl-table-cell"></th>
        </tr>
      </thead>
    </React.Fragment>
  );
};

export default ProjectHeader;
