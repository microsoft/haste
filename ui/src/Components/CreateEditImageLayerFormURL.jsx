// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState } from "react";
import { TextField, PrimaryButton } from "@fluentui/react";
import propTypes from "prop-types";
import { addUrlToEventImageryArray } from "./CreateEditImageLayerHelper";

const CreateEditImageLayerFormURL = ({
  setComponentState,
  componentState,
  field,
  currentEventImageryUrlControl,
  imageLayerId,
}) => {
  CreateEditImageLayerFormURL.propTypes = {
    setComponentState: propTypes.func.isRequired,
    componentState: propTypes.object.isRequired,
    field: propTypes.string.isRequired,
    currentEventImageryUrlControl: propTypes.string.isRequired,
    imageLayerId: propTypes.string,
  };

  const [url, setUrl] = useState("");

  function handleAddition() {
    if (
      addUrlToEventImageryArray(
        setComponentState,
        componentState,
        url,
        field,
        currentEventImageryUrlControl + "Error"
      )
    ) {
      setUrl("");
    }
  }

  return (
    <React.Fragment>
      <TextField
        className="flex-grow-1 me-2"
        placeholder="Write or paste a URL"
        onChange={(e) => setUrl(e.target.value)}
        errorMessage={componentState[currentEventImageryUrlControl + "Error"]}
        value={url}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            handleAddition();
          }
        }}
        disabled={imageLayerId ? true : false}
      />
      <PrimaryButton onClick={handleAddition} disabled={!url}>
        Add
      </PrimaryButton>
    </React.Fragment>
  );
};

export default CreateEditImageLayerFormURL;
