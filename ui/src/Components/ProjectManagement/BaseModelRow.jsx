// Components
import {
  Text,
  Tooltip,
  Button,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
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
        icon: <FluentIcon name="Edit" />,
      },
      {
        key: "remove",
        text: "Remove",
        icon: <FluentIcon name="Delete" />,
      },
    ],
  };

  return (
    <React.Fragment>
      <tr key={item.userId}>
        <td className="">
          <Text className="pe-4">
          {item.name}
          </Text>
        </td>
        <td>
          <Text className="pe-4 ellipsis">
            <Tooltip content={item.email} relationship="label">
              <span>{item.sourceURL}</span>
            </Tooltip>
          </Text>
        </td>
        <td>
          <Text className="pe-4">
          {item.creationDate}
          </Text>
        </td>
        <td>
          <Menu positioning="below-end">
            <MenuTrigger disableButtonEnhancement>
              <Button
                appearance="subtle"
                className="no-dropdown-icon"
                icon={<FluentIcon name="More" />}
                title="Menu"
                aria-label="Menu"
              />
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                {moreMenuOptions.items.map((mi) => (
                  <MenuItem
                    key={mi.key}
                    className={mi.className}
                    icon={mi.icon}
                    disabled={mi.disabled}
                    onClick={mi.onClick}
                  >
                    {mi.text}
                  </MenuItem>
                ))}
              </MenuList>
            </MenuPopover>
          </Menu>
        </td>
      </tr>
    </React.Fragment>
  );
};

export default BaseModelRow;
