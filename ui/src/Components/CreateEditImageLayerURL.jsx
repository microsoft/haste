// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React from "react";
import propTypes from "prop-types";

import { Link, Button } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";

import { removeUrlFromEventImageryArray } from "./CreateEditImageLayerHelper";
import { safeHref } from "../util/validation";

const CreateEditImageLayerURL = ({
  setComponentState,
  componentState,
  url,
  field,
  imageLayerId
}) => {
  CreateEditImageLayerURL.propTypes = {
    setComponentState: propTypes.func.isRequired,
    componentState: propTypes.object.isRequired,
    url: propTypes.object.isRequired,
    field: propTypes.string.isRequired,
    imageLayerId: propTypes.string,
  };

  return (
    <React.Fragment>
      <div className="col-12 d-flex align-items-center">
        <div className="col flex-grow-1 me-2">
          <Link
            href={safeHref(url.value)}
            target="_blank"
            rel="noopener noreferrer"
            className="custom-text-wrap pe-4"
            style={{ fontSize: "14px" }}
          >
            {url.name ? url.name : url.value}
          </Link>
        </div>
        <div className="col-auto d-flex align-items-center">
          <Button
            appearance="subtle"
            icon={<FluentIcon name="Delete" />}
            aria-label="Delete"
            onClick={() =>
              removeUrlFromEventImageryArray(
                url.id,
                setComponentState,
                componentState,
                field
              )
            }
            disabled={imageLayerId ? true : false}
          />
        </div>
      </div>
    </React.Fragment>
  );
};

export default CreateEditImageLayerURL;
