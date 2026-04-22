// Components
import { IconButton, Text, TooltipHost } from "@fluentui/react";
import React from "react";

import PropTypes from "prop-types";

const BaseModelRow = ({item}) => {
  BaseModelRow.propTypes = {
    item: PropTypes.object.isRequired,
  };

  const moreMenuOptions = {
    items: [
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
      <tr key={item.userId}>
        <td className="">
          <Text variant="medium" className="pe-4">
          {item.name}
          </Text>
        </td>
        <td>
          <Text variant="medium" className="pe-4 ellipsis">
            <TooltipHost content={item.email} delay={200}>
            {item.sourceURL}
            </TooltipHost>
          </Text>
        </td>
        <td>
          <Text variant="medium" className="pe-4">
          {item.creationDate}
          </Text>
        </td>
        <td>
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

export default BaseModelRow;
