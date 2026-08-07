// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState } from "react";
import { Input, Button, Field } from "@fluentui/react-components";
import propTypes from "prop-types";
import { addFileToEventImageryArray } from "./CreateEditImageLayerHelper";
import { v4 as uuidv4 } from "uuid";

const CreateEditImageLayerFormFile = ({
  setComponentState,
  componentState,
  field,
  currentEventImageryUrlControl,
  imageLayerId
}) => {
  CreateEditImageLayerFormFile.propTypes = {
    setComponentState: propTypes.func.isRequired,
    componentState: propTypes.object.isRequired,
    field: propTypes.string.isRequired,
    currentEventImageryUrlControl: propTypes.string.isRequired,
    imageLayerId: propTypes.string,
  };

  const [files, setFiles] = useState("");
  const acceptedFileTypes = ["tif", "tiff", "geotiff"];
  const uniqueId = useState(uuidv4());

  function hanfleFileInputOpen() {
    const fileInput = document.getElementById("fileInput" + uniqueId);
    fileInput.click();
    fileInput.onchange = (e) => {
      if (e.target.files.length > 0) {
        setFiles(e.target.files);
      }
    };
  }

  function handleFileAddition() {
    addFileToEventImageryArray(
      files,
      acceptedFileTypes,
      componentState,
      setComponentState,
      field,
      currentEventImageryUrlControl + "Error"
    );
    setFiles("");
    document.getElementById("fileInput" + uniqueId).value = null;
  }

  return (
    <React.Fragment>
      <input
        type="file"
        multiple={true}
        accept={acceptedFileTypes.map((type) => `.${type}`).join(",")}
        onChange={(e) => {
          if (e.target.files.length > 0) {
            setFiles(e.target.files);
          } else {
            setFiles("");
          }
        }}
        className="d-none"
        id={"fileInput" + uniqueId}
        aria-label="File Input"
      />
      <Field
        className="flex-grow-1 me-2 cursor-pointer-on-hover"
        validationMessage={componentState[currentEventImageryUrlControl + "Error"]}
      >
        <Input
          placeholder="Click here to select one or more files"
          value={
            files && files.length === 1
              ? files[0].name
              : files && files.length > 1
              ? `${files.length} files selected`
              : ""
          }
          onClick={hanfleFileInputOpen}
          readOnly={true}
          disabled={imageLayerId ? true : false}
        />
      </Field>
      <Button appearance="primary" onClick={handleFileAddition} disabled={!files}>
        Upload
      </Button>
    </React.Fragment>
  );
};

export default CreateEditImageLayerFormFile;
