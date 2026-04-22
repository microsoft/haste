// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  IconButton,
  Text
} from "@fluentui/react";
import PropTypes from "prop-types";

const PaginationControls = ({ totalPages, currentPage, setCurrentPage }) => {
  PaginationControls.propTypes = {
    totalPages: PropTypes.number.isRequired,
    currentPage: PropTypes.number.isRequired,
    setCurrentPage: PropTypes.func.isRequired,
  };


  return (
    <>
      {totalPages > 1 && (
        <div className="d-flex justify-content-center align-items-center mt-5">
          <IconButton
            iconProps={{ iconName: "ChevronLeft" }}
            disabled={currentPage === 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            style={{ marginRight: 8 }}
          />
          <Text variant="small">
            {currentPage} of {totalPages}
          </Text>
          <IconButton
            iconProps={{ iconName: "ChevronRight" }}
            disabled={currentPage === totalPages}
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            style={{ marginLeft: 8 }}
          />
        </div>
      )}
    </>
  );
};

export default PaginationControls;
