// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext } from "react";
import {
  Checkbox,
  Dropdown,
  Text
} from "@fluentui/react";

import { apiGet } from "../util/api";
import { updateUserSettings } from "../AppHelper";
import { AppContext } from "../AppContext";
import SectionModal from "./SectionModal";
import proptypes from "prop-types";

const SettingsModal = ({ onClose }) => {
  SettingsModal.propTypes = {
    onClose: proptypes.func.isRequired,
  };


  const { appParams, setIsLoading, setAppParams } = useContext(AppContext);

  async function handleGuidedTourToggle() {
    setIsLoading(true, "Toggling Guided Tour...");
    var response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ disableGuidedTour: !appParams.userSettings.disableGuidedTour }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        disableGuidedTour: !prevParams.userSettings.disableGuidedTour,
      },
    }));
    setIsLoading(false);
  }

  async function handleItemsPerPageChange(event, option) {
    setIsLoading(true, "Updating Items Per Page...");
    var response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ itemsPerPage: option.key }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        itemsPerPage: option.key,
      },
    }));
    setIsLoading(false);
  }

  return (
    <SectionModal
      title={"Settings"}
      body={
        <>
          <div className="row mb-2">
            <div className="col-12">

            </div>
          </div>
          <div className="row mb-2 d-flex flex-column">
            <div className="col-12 d-flex flex-column mb-3">
              <Checkbox
                label="Guided Tour"
                checked={!appParams.userSettings.disableGuidedTour}
                onChange={handleGuidedTourToggle}
              />
              <Text className="pt-2" variant="small">
                When enabled, will provide step-by-step instructions to help you navigate through the application.
              </Text>
            </div>
            <hr />
            <div className="col-12 d-flex flex-column">
              <Dropdown
                label="Items per page in tables"
                selectedKey={appParams.userSettings.itemsPerPage ?? 10}
                options={[
                  { key: 5, text: "5" },
                  { key: 8, text: "8" },
                  { key: 10, text: "10" },
                  { key: 20, text: "20" },
                  { key: 50, text: "50" },
                ]}
                onChange={handleItemsPerPageChange}
                style={{width: 'fit-content'}}
              />
              <Text className="pt-2" variant="small">
                Defines how many items are displayed per page in tables throughout the application.
              </Text>
            </div>
          </div>
        </>
      }
      onClose={onClose}
      icon="Settings"
    />
  );
};

export default SettingsModal;
