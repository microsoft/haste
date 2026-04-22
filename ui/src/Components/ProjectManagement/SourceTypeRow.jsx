// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton, Text, TooltipHost } from "@fluentui/react";
import React from "react";
import { limitTextLength } from "../../util/conversion";

import PropTypes from "prop-types";

const SourceTypeRow = ({ item, moreInfoVisibleId, setMoreInfoVisibleId }) => {
  SourceTypeRow.propTypes = {
    item: PropTypes.object.isRequired,
    moreInfoVisibleId: PropTypes.number,
    setMoreInfoVisibleId: PropTypes.func.isRequired,
  };

  const moreMenuOptions = {
    items: [
      {
        key: "info",
        className: "d-block d-lg-none",
        text: moreInfoVisibleId === item.sourceTypeId ? "Hide Info" : "View Info",
        iconProps: { iconName: moreInfoVisibleId === item.sourceTypeId ? "Cancel" : "Info" },
        onClick: () => {
          if (moreInfoVisibleId === item.sourceTypeId) {
            setMoreInfoVisibleId(null);
          } else {
            setMoreInfoVisibleId(item.sourceTypeId);
          }
        },
      },
      {
        key: "edit",
        text: "Edit",
        iconProps: { iconName: "Edit" },
      },
      {
        key: "remove",
        text: "Remove",
        iconProps: { iconName: "Delete" },
      },
    ],
  };

  return (
    <React.Fragment>
      <tr key={item.sourceTypeId}>
        <td className="">
          <Text variant="medium" className="pe-4">
            {limitTextLength(item.name, 50, 55)}
          </Text>

          {moreInfoVisibleId == item.sourceTypeId && (<>
            <Text variant="small">
              <table className="col-12 dashboard-inner-table p-3 mt-2">
                <tbody>
                  <tr>
                    <td>
                      <div className="pb-2">
                        <Text
                          variant="small"
                          className="me-4 fw-semibold custom-text-color"
                        >
                          Source Type Info:
                        </Text>
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td >
                      <span className="fw-semibold">Base URL: </span>{item.baseURL}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Creation Date: </span> {item.creationDate}
                    </td>
                  </tr>
                </tbody>
              </table>
            </Text>
          </>
          )}

        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text variant="medium" className="pe-4 ellipsis">
            <TooltipHost content={item.baseURL} delay={200}>
              {item.baseURL}
            </TooltipHost>
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text variant="medium" className="pe-4">
            {item.creationDate}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-flex align-items-start align-items-md-center justify-content-end">
          <IconButton
            className="no-dropdown-icon"
            menuProps={moreMenuOptions}
            iconProps={{ iconName: "more" }}
            title="Menu"
            ariaLabel="Menu"
          />
        </td>
      </tr>
    </React.Fragment>
  );
};

export default SourceTypeRow;
