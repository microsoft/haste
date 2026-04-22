// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton, Text, TooltipHost, Link } from "@fluentui/react";

import PropTypes from "prop-types";
import { apiDelete } from "../../util/api";
import { AppContext } from "../../AppContext";
import { limitTextLength } from "../../util/conversion";
import ModelCatalogAdditionalInfoModal from "./ModelCatalogAdditionalInfoModal";

import React from "react";

const ModelCatalogRow = ({ item, index, setModalComponent, fetchModels, moreInfoVisibleId, setMoreInfoVisibleId }) => {
  ModelCatalogRow.propTypes = {
    item: PropTypes.object.isRequired,
    index: PropTypes.number.isRequired,
    setModalComponent: PropTypes.func,
    fetchModels: PropTypes.func.isRequired,
    moreInfoVisibleId: PropTypes.string,
    setMoreInfoVisibleId: PropTypes.func,
  };

  const { setDialog, setIsLoading } = React.useContext(AppContext);

  const moreMenuOptions = {
    items: [
      {
        key: "info",
        className: "d-block d-lg-none",
        text: moreInfoVisibleId === item.modelId ? "Hide Info" : "View Info",
        iconProps: { iconName: moreInfoVisibleId === item.modelId ? "Cancel" : "Info" },
        onClick: () => {
          if (moreInfoVisibleId === item.modelId) {
            setMoreInfoVisibleId(null);
          } else {
            setMoreInfoVisibleId(item.modelId);
          }
        },
      },
      {
        key: "remove",
        text: "Remove",
        iconProps: { iconName: "Delete" },
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
        <td className="custom-text-no-wrap">
          <TooltipHost content={item.baseModelName} delay={2}>
            <Text variant="medium" className="pe-4 d-flex flex-column" id={"modelCatalogName" + index}>
              {limitTextLength(item.baseModelName, false, 55)}
            </Text>
          </TooltipHost>
        </td>

        <td className="custom-text-no-wrap d-none d-lg-table-cell">
          <Text
            variant="medium"
            className="pe-4 ellipsis"
            id={"modelCatalogDescription" + index}
          >
            <TooltipHost content={item.description} delay={2}>
              {limitTextLength(item.description, 80, 70)}
            </TooltipHost>
          </Text>
        </td>

        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"modelCatalogSource" + index}
          >
            {item.imagerySource}
          </Text>
        </td>
        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"modelCatalogEventType" + index}
          >
            {Array.isArray(item.eventTypes) && item.eventTypes.length > 0 ? item.eventTypes.join(", ") : "--"}
          </Text>
        </td>

        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"modelCatalogCataloguedDate" + index}
          >
            {item.cataloguedDate.substring(0, 10) +
              " " +
              item.cataloguedDate.substring(11, 19)}
          </Text>
        </td>

        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
            className="pe-4"
            id={"modelCatalogCataloguedByUser" + index}
          >
            {item.cataloguedByUser}
          </Text>
        </td>

        <td className="custom-text-no-wrap d-none d-xl-table-cell">
          <Text
            variant="medium"
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

        <td className="custom-text-no-wrapca d-flex align-items-start align-items-md-center justify-content-end">
          <IconButton
            id={"projectsMoreOptions" + index}
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

export default ModelCatalogRow;
