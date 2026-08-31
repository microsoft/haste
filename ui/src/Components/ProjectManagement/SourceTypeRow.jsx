// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
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
import { limitTextLength } from "../../util/conversion";

import PropTypes from "prop-types";

const SourceTypeRow = ({ item, moreInfoVisibleId, setMoreInfoVisibleId }) => {
  SourceTypeRow.propTypes = {
    item: PropTypes.object.isRequired,
    moreInfoVisibleId: PropTypes.number,
    setMoreInfoVisibleId: PropTypes.func.isRequired,
  };

  // Breakpoint at which the responsive info row stops being needed, because
  // the Base URL and Creation Date columns are visible in the table itself.
  // The menu trigger below is hidden at the same breakpoint: every item in
  // this menu is mobile-only, so leaving the trigger up on desktop would
  // open an empty popover. Keep the two in sync if an always-visible item
  // is ever added here.
  const MOBILE_ONLY = "d-lg-none";

  const moreMenuOptions = {
    items: [
      {
        key: "info",
        className: `d-block ${MOBILE_ONLY}`,
        text: moreInfoVisibleId === item.sourceTypeId ? "Hide Info" : "View Info",
        icon: <FluentIcon name={moreInfoVisibleId === item.sourceTypeId ? "Cancel" : "Info"} />,
        onClick: () => {
          if (moreInfoVisibleId === item.sourceTypeId) {
            setMoreInfoVisibleId(null);
          } else {
            setMoreInfoVisibleId(item.sourceTypeId);
          }
        },
      },
    ],
  };

  return (
    <React.Fragment>
      <tr key={item.sourceTypeId}>
        <td className="">
          <Text className="pe-4">
            {limitTextLength(item.name, 50, 55)}
          </Text>

          {moreInfoVisibleId == item.sourceTypeId && (<>
            <Text size={200}>
              <table className="col-12 dashboard-inner-table p-3 mt-2">
                <tbody>
                  <tr>
                    <td>
                      <div className="pb-2">
                        <Text
                          size={200}
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
          <Text className="pe-4 ellipsis">
            <Tooltip content={item.baseURL} relationship="label">
              <span>{item.baseURL}</span>
            </Tooltip>
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text className="pe-4">
            {item.creationDate}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-flex align-items-start align-items-md-center justify-content-end">
          <span className={MOBILE_ONLY}>
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
          </span>
        </td>
      </tr>
    </React.Fragment>
  );
};

export default SourceTypeRow;
