// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Text } from "@fluentui/react-components";
import PropTypes from "prop-types";

const NoResults = ({ items, text }) => {

  NoResults.propTypes = {
    items: PropTypes.array.isRequired,
    text: PropTypes.string.isRequired,
  };

  return (
    <>
      {items.length === 0 && (
        <div className="d-flex align-items-center justify-content-center h-100">
          <Text>{text}</Text>
        </div>
      )}
    </>
  );
};



export default NoResults;