// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState, useEffect } from "react";
import propTypes from "prop-types";
import { Text } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { Button } from "@fluentui/react-components";
import { convertFileIntoUrl, removeUrlFromEventImageryArray } from "./CreateEditImageLayerHelper";
import { apiPost } from "../util/api";

import ProgressBar from "./OtherComponents/ProgressBar";

const CreateEditImageLayerFileUploader = ({
  setComponentState,
  componentState,
  file,
  field,
  dataFormat
}) => {
  CreateEditImageLayerFileUploader.propTypes = {
    setComponentState: propTypes.func.isRequired,
    componentState: propTypes.object.isRequired,
    file: propTypes.object.isRequired,
    field: propTypes.string.isRequired,
    dataFormat: propTypes.string
  };

  const [progress, setProgress] = useState("");
  const [fileUrl, setFileUrl] = useState(null);
  useEffect(() => {
    if (file) {
      uploadFile();
    }
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (fileUrl) {
      convertFileIntoUrl(setComponentState, componentState, file, fileUrl, field);
    }

  // eslint-disable-next-line
  }, [fileUrl]);

  const uploadFile = async () => {
    if (!file) return;
    if (!componentState?.projectId) {
      setProgress("Error");
      console.error("Missing projectId while uploading file chunks.");
      return;
    }
    var tempFileUrl = "";
    const chunkSize = 4 * 1024 * 1024;
    const totalChunks = Math.ceil(file.value.size / chunkSize);

    setProgress("Starting");
    for (let start = 0; start < file.value.size; start += chunkSize) {
      const chunk = file.value.slice(start, start + chunkSize);
      const formData = new FormData();
      formData.append("project_id", componentState.projectId);
      formData.append("file_id", file.id);
      formData.append("chunk_number", start / chunkSize);
      formData.append("total_chunks", totalChunks);
      formData.append("chunk", chunk);
      formData.append("action", "add | cancel");
      if (dataFormat) {
        formData.append("data_format", dataFormat);
      }

      try {
        const response = await apiPost("UploadFileByChunk", formData, true);
        if (!response) {
          console.error(`Failed to upload chunk ${start / chunkSize}`);
          break;
        }

        if (response.outputUrl) {
          tempFileUrl = response.outputUrl;
        }

        setProgress(
          (((start + chunkSize) / file.value.size) * 100).toFixed(2)
        );
      } catch (error) {
        setProgress("Error");
        console.error(`Error uploading chunk ${start / chunkSize}:`, error);
        break;
      }
    }

    setFileUrl(tempFileUrl);
  };

  return (
    <React.Fragment>
      <div className="col-12 d-flex flex-column flex-lg-row align-items-start- align-items-lg-center">
        <div className="col flex-grow-1 me-2">
          <Text>{file.value.name}</Text>
        </div>
        <div className="col-auto d-flex align-items-center mt-2 mt-lg-0">
          <ProgressBar
            progress={progress}
          />
          <Button
            appearance="subtle"
            icon={<FluentIcon name="Delete" />}
            aria-label="Delete"
            onClick={() =>
              removeUrlFromEventImageryArray(
                file.id,
                setComponentState,
                componentState,
                field
              )
            }
          />
        </div>
      </div>
    </React.Fragment>
  );
};

export default CreateEditImageLayerFileUploader;
