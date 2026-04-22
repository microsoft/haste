// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React from "react";
import { TextField, IconButton } from "@fluentui/react";

import {
  onChangePrimaryClass,
  removePrimaryClass,
} from "./CreateEditProjectModalHelper";

import proptypes from "prop-types";
import CustomColorPicker from "./OtherComponents/ColorPicker";

const PrimaryClassCreator = ({
  primaryClass,
  index,
  setComponentState,
  componentState,
  projectId,
  setDialog,
}) => {
  PrimaryClassCreator.propTypes = {
    primaryClass: proptypes.object.isRequired,
    index: proptypes.number.isRequired,
    setComponentState: proptypes.func.isRequired,
    componentState: proptypes.object.isRequired,
    projectId: proptypes.string,
    setDialog: proptypes.func.isRequired,
  };

  return (
    <React.Fragment key={"primaryClass" + index}>
      <div className="col-12 flex-column flex-md-row d-flex pt-1 mb-1">
        <TextField
          disabled={projectId !== undefined}
          label="Name"
          className="me-2 flex-grow-1"
          value={primaryClass.name}
          maxLength={25}
          onChange={(e) => {
            const filteredValue = e.target.value.replace(/[^A-Za-z0-9\-_\s]/g, "");
            onChangePrimaryClass(
              index,
              "name",
              filteredValue,
              setComponentState,
              componentState
            );
          }}
        />
        <div className="d-flex align-items-end">
          <CustomColorPicker
            disabled={projectId !== undefined}
            labelText={"Color"}
            color={primaryClass.color}
            category={"label"}
            field={"damagedBuildingFillColor"}
            onFormChange={(color) =>
              onChangePrimaryClass(
                index,
                "color",
                color,
                setComponentState,
                componentState
              )
            }
          />

          {projectId === undefined && (
            <IconButton
              aria-label="RemovePrimaryClass"
              iconProps={{ iconName: "Delete" }}
              onClick={() =>
                removePrimaryClass(
                  index,
                  setComponentState,
                  componentState,
                  setDialog
                )
              }
              className="ms-2"
            />
          )}
        </div>
      </div>
    </React.Fragment>
  );
};

export default PrimaryClassCreator;
