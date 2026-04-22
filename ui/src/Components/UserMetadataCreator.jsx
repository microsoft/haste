// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React from "react";
import { TextField, IconButton } from "@fluentui/react";

import {
  onChangeMetadata,
  removeMetadata,
} from "./CreateEditModelCheckpointHelper";

import proptypes from "prop-types";


const UserMetadataCreator = ({
  metadata,
  index,
  setComponentState,
  componentState,
}) => {
  UserMetadataCreator.propTypes = {
    metadata: proptypes.object.isRequired,
    index: proptypes.number.isRequired,
    setComponentState: proptypes.func.isRequired,
    componentState: proptypes.object.isRequired,
  };

  return (
    <React.Fragment key={"metadata" + index}>
      <div className="row" key={index}>
        <div className="col-12 align-items-end justify-content-center p- gap-0 gap-lg-2">
          <div className="col-12">
            <TextField
              id={`userMetadata${index}`}
              label="Key"
              value={metadata.key}
              maxLength={50}
              onChange={(e) => {
                const filteredValue = e.target.value.replace(/[^A-Za-z0-9\-_\s]/g, "");
                onChangeMetadata(
                  index,
                  "key",
                  filteredValue,
                  setComponentState,
                  componentState
                );
              }}
            />
          </div>
          <div className="col-12 d-flex align-items-end gap-2 ">
            <TextField
              label="Value"
              value={metadata.value}
              maxLength={250}
              autoAdjustHeight
              multiline
              className="flex-grow-1"
              onChange={(e) => {
                const filteredValue = e.target.value.replace(/[^A-Za-z0-9\-_\s]/g, "");
                onChangeMetadata(
                  index,
                  "value",
                  filteredValue,
                  setComponentState,
                  componentState
                );
              }}
            />

            <IconButton
              iconProps={{ iconName: "Delete" }}
              title="Remove Metadata"
              ariaLabel="Remove Metadata"
              onClick={() =>
                removeMetadata(index, setComponentState, componentState)
              }
            />
          </div>
        <hr className="col-12 mt-4 mb-3" />
        </div>
        
      </div>
    </React.Fragment>
  );
};

export default UserMetadataCreator;
