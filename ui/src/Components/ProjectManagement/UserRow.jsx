// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton, on, Text, TooltipHost } from "@fluentui/react";
import React, { useContext } from "react";

import { apiDelete } from "../../util/api";
import PropTypes from "prop-types";
import { AppContext } from "../../AppContext";
import CreateEditUserModal from "../CreateEditUserModal";
import { limitTextLength } from "../../util/conversion";
import { apiPut } from "../../util/api";

const UserRow = ({ item, index, setModalComponent, moreInfoVisibleId, setMoreInfoVisibleId }) => {
  UserRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    moreInfoVisibleId: PropTypes.string,
    setMoreInfoVisibleId: PropTypes.func.isRequired,
  };

  const { setDialog, setIsLoading } = useContext(AppContext);

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
        key: "info",
        className: "d-block d-lg-none",
        text: moreInfoVisibleId === item.email ? "Hide Info" : "View Info",
        iconProps: { iconName: moreInfoVisibleId === item.email ? "Cancel" : "Info" },
        onClick: () => {
          if (moreInfoVisibleId === item.email) {
            setMoreInfoVisibleId(null);
          } else {
            setMoreInfoVisibleId(item.email);
          }
        },
      },
      {
        key: "re-send-invitation",
        text: "Re-send Invitation",
        iconProps: { iconName: "MailForward" },
        disabled: item.status !== "PendingAcceptance",
        onClick: () => reSendInvitation(item),
      },
      {
        key: "edit",
        text: "Edit",
        iconProps: { iconName: "Edit" },
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
        iconProps: { iconName: "Delete" },
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
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text variant="medium" className="pe-4 ellipsis">
            <TooltipHost content={item.name === "" ? "--" : item.name} delay={200}>
              {item.name === "" ? "--" : item.name}
            </TooltipHost>
          </Text>

        </td>
        <td className="ellipsis">
          <Text variant="medium" className="pe-4 ellipsis">
            <TooltipHost content={item.email} delay={200}>
              {limitTextLength(item.email, 50, 55)}
            </TooltipHost>
          </Text>

          {moreInfoVisibleId == item.email && (<>
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
                          User Info:
                        </Text>
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Name: </span>{item.name === "" ? "--" : item.name}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">User Roles: </span> {item.userRoles.join(", ")}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span className="fw-semibold">Status: </span> {item.status}
                    </td>
                  </tr>
                </tbody>
              </table>
            </Text>
          </>
          )}

        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text variant="medium" className="pe-4">
            {item.userRoles.join(", ")}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text variant="medium" className="pe-4">
            {item.status}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-flex align-items-start align-items-md-center justify-content-end">
          {item.status != "Inactive" &&
            <IconButton
              className="no-dropdown-icon"
              menuProps={moreMenuOptions}
              iconProps={{ iconName: "more" }}
              title="Menu"
              ariaLabel="Menu"
            />
          }

        </td>
      </tr>
    </React.Fragment>
  );
};

export default UserRow;
