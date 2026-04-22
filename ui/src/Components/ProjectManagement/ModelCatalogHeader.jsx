// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react";

import React from "react";

const ModelCatalogHeader = () => {
  return (
    <React.Fragment>
      <thead id="singleProjectTable">
        <tr>
          <th className="pb-3 pe-4 custom-text-no-wrap">
            <Text className="fw-semibold">Base Model Name</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Description</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Source</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Event Type</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Catalogued Date</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xl-table-cell">
            <Text className="fw-semibold">Catalogued By</Text>
          </th>
          <th className="pb-3 pe-4 custom-text-no-wrap d-none d-xxl-table-cell">
            <Text className="fw-semibold">Metadata</Text>
          </th>
          <th className="pb-3 d-none d-xl-table-cell"></th>
        </tr>
      </thead>
    </React.Fragment>
  );
};

export default ModelCatalogHeader;
