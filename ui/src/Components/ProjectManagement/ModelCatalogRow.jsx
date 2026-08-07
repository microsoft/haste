// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Text,
  Tooltip,
  Link,
  Button,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import PropTypes from "prop-types";
import { apiDelete } from "../../util/api";
import { AppContext } from "../../AppContext";
import { limitTextLength } from "../../util/conversion";
import ModelCatalogAdditionalInfoModal from "./ModelCatalogAdditionalInfoModal";

import React from "react";

const ModelCatalogRow = ({ item, index, setModalComponent, fetchModels }) => {
  ModelCatalogRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    setModalComponent: PropTypes.func,
    fetchModels: PropTypes.func.isRequired,
  };

  const { setDialog, setIsLoading } = React.useContext(AppContext);

  const moreMenuOptions = {
    items: [
      {
        key: "remove",
        text: "Remove",
        icon: <FluentIcon name="Delete" />,
        onClick: () => {
          setDialog(
            "Important",
            `Do you want to remove the model "${item.baseModelName}" from Catalog?`,
            [
              {
                type: "primary",
                key: "yes",
                text: "Yes",
                onClick: () => handleDeletion(item.modelId),
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
      }
    ],
  };

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function handleDeletion(modelId) {

    const buttons = [
      {
        type: "primary",
        key: "close",
        text: "Close",
        onClick: () => setDialog(),
      },
    ];

    try {
      setDialog();
      setIsLoading(true, "Removing Model from Catalog...");
      await apiDelete(`DeleteModelCatalog?modelId=${modelId}`);
      await sleep(2000);
      await fetchModels();
      setDialog("Success", "Model removed successfully.", buttons);
    } catch (error) {
      setDialog("Error", "Error removing model from Catalog, Please try again later.", buttons);
    }
    setIsLoading(false);
  }

  function handleAdditionalInfoDisplay(additionalInfo) {
    setModalComponent(
      <ModelCatalogAdditionalInfoModal
        onClose={() => setModalComponent(null)}
        additionalInfo={additionalInfo}
      />
    );
  }



  return (
    <React.Fragment>
      <tr>
        <td className="custom-text-no-wrap" data-label="Base Model Name">
          <Tooltip content={item.baseModelName} relationship="label">
            <Text
              className="pe-4 model-catalog-name"
              id={"modelCatalogName" + index}
            >
              {item.baseModelName}
            </Text>
          </Tooltip>
        </td>

        <td className="custom-text-no-wrap" data-label="Description">
          <Text
            className="pe-4 ellipsis"
            id={"modelCatalogDescription" + index}
          >
            <Tooltip content={item.description} relationship="label">
              <span>{limitTextLength(item.description, 80, 70)}</span>
            </Tooltip>
          </Text>
        </td>

        <td className="custom-text-no-wrap" data-label="Source">
          <Text
            className="pe-4"
            id={"modelCatalogSource" + index}
          >
            {item.imagerySource}
          </Text>
        </td>
        <td className="custom-text-no-wrap" data-label="Event Type">
          <Text
            className="pe-4"
            id={"modelCatalogEventType" + index}
          >
            {Array.isArray(item.eventTypes) && item.eventTypes.length > 0 ? item.eventTypes.join(", ") : "--"}
          </Text>
        </td>

        <td className="custom-text-no-wrap" data-label="Catalogued Date">
          <Text
            className="pe-4"
            id={"modelCatalogCataloguedDate" + index}
          >
            {item.cataloguedDate.substring(0, 10) +
              " " +
              item.cataloguedDate.substring(11, 19)}
          </Text>
        </td>

        <td className="custom-text-no-wrap" data-label="Catalogued By">
          <Text
            className="pe-4"
            id={"modelCatalogCataloguedByUser" + index}
          >
            {item.cataloguedByUser}
          </Text>
        </td>

        <td className="custom-text-no-wrap" data-label="Metadata">
          <Text
            className="pe-4"
            id={"modelCatalogAdditionalInfo" + index}
          >
            {item.additionalInfo !== null &&
              item.additionalInfo !== undefined &&
              !(typeof item.additionalInfo === "object" && Object.keys(item.additionalInfo).length === 0) ?
              <Link onClick={() => handleAdditionalInfoDisplay(item.additionalInfo)}>
                View Metadata
              </Link>
              :
              "--"}
          </Text>
        </td>

        <td className="custom-text-no-wrapca pgrid-action-cell" data-label="">
          <Menu positioning="below-end">
            <MenuTrigger disableButtonEnhancement>
              <Button
                id={"projectsMoreOptions" + index}
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

export default ModelCatalogRow;
