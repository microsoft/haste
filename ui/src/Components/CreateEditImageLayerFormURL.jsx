// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState } from "react";
import { Input, Button, Field } from "@fluentui/react-components";
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
      <Field
        className="flex-grow-1 me-2"
        validationMessage={componentState[currentEventImageryUrlControl + "Error"]}
      >
        <Input
          placeholder="Write or paste a URL"
          onChange={(e, data) => setUrl(data.value)}
          value={url}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              handleAddition();
            }
          }}
          disabled={imageLayerId ? true : false}
        />
      </Field>
      <Button appearance="primary" onClick={handleAddition} disabled={!url}>
        Add
      </Button>
    </React.Fragment>
  );
};

export default CreateEditImageLayerFormURL;
