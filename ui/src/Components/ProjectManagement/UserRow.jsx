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
import React, { useContext } from "react";

import { apiDelete } from "../../util/api";
import PropTypes from "prop-types";
import { AppContext } from "../../AppContext";
import CreateEditUserModal from "../CreateEditUserModal";
import { limitTextLength } from "../../util/conversion";
import { apiPut } from "../../util/api";

/** Map a user status to a pill badge label + tone. */
function getUserStatusBadge(status) {
  if (status === "Active") return { label: "Active", tone: "active" };
  if (status === "PendingAcceptance")
    return { label: "Pending", tone: "pending" };
  if (status === "Inactive") return { label: "Inactive", tone: "inactive" };
  return { label: status || "—", tone: "inactive" };
}

const UserRow = ({ item, index, setModalComponent }) => {
  UserRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    setModalComponent: PropTypes.func.isRequired,
  };

  const { setDialog, setIsLoading } = useContext(AppContext);
  const statusBadge = getUserStatusBadge(item.status);

  async function handleDeletion() {
    setIsLoading(true);
    await apiDelete(`DeleteUser?userId=${item.userId}`)
      .then(() => {
        window.location.reload();
      })
      .catch((error) => {
        console.error("Error deleting user:", error);
      });
    setIsLoading(false);
  }

  async function reSendInvitation(item) {
    const buttons = [
      {
        type: "primary",
        key: "close",
        text: "Close",
        onClick: () => {
          setDialog("", "", []);
        },
      },
    ];

    setIsLoading(true, "Re-sending invitation...");

    try {
      await apiPut("PutUser", { user: item, action: "reinvite" });
      setIsLoading(false);
      setDialog("Success", "The invitation has been re-sent.", buttons);

    } catch (error) {
      setIsLoading(false);
      setDialog(
        "Error",
        "There was an error re-sending the invitation. Please try again later.",
        []
      );
    }
  }

  const moreMenuOptions = {
    items: [
      {
        key: "re-send-invitation",
        text: "Re-send Invitation",
        icon: <FluentIcon name="MailForward" />,
        disabled: item.status !== "PendingAcceptance",
        onClick: () => reSendInvitation(item),
      },
      {
        key: "edit",
        text: "Edit",
        icon: <FluentIcon name="Edit" />,
        onClick: () => {
          setModalComponent(
            <CreateEditUserModal
              onClose={() => setModalComponent(null)}
              userToEdit={item}
            />
          );
        },
      },
      {
        key: "remove",
        text: "Remove",
        icon: <FluentIcon name="Delete" />,
        onClick: () => {
          setDialog(
            "Important",
            `Do you want to delete the user "${item.name}"?.`,
            [
              {
                type: "primary",
                key: "yes",
                text: "Yes",
                onClick: handleDeletion,
              },
              {
                type: "default",
                key: "no",
                text: "No",
                onClick: () => setDialog(),
              },
            ]
          );
        },
      },
    ],
  };

  return (
    <React.Fragment key={index}>
      <tr className={item.status === "Inactive" ? "table-row-inactive" : ""} >
        <td className="custom-text-no-wrap" data-label="Name">
          <Text className="pe-4 ellipsis">
            <Tooltip content={item.name === "" ? "--" : item.name} relationship="label">
              <span>{item.name === "" ? "--" : item.name}</span>
            </Tooltip>
          </Text>

        </td>
        <td className="ellipsis" data-label="E-mail">
          <Text className="pe-4 ellipsis">
            <Tooltip content={item.email} relationship="label">
              <span>{limitTextLength(item.email, 50, 55)}</span>
            </Tooltip>
          </Text>
        </td>
        <td className="custom-text-no-wrap" data-label="User Roles">
          <Text className="pe-4">
            {item.userRoles.join(", ")}
          </Text>
        </td>
        <td className="custom-text-no-wrap" data-label="Status">
          <span className={`pgrid-pill pgrid-pill--${statusBadge.tone}`}>
            <span className="pgrid-pill-dot" />
            {statusBadge.label}
          </span>
        </td>
        <td
          className="custom-text-no-wrap d-flex align-items-start align-items-md-center justify-content-end"
          data-label="Actions"
        >
          {item.status != "Inactive" &&
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
          }

        </td>
      </tr>
    </React.Fragment>
  );
};

export default UserRow;
