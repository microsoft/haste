// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Button, Text } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
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
          <Button
            appearance="subtle"
            icon={<FluentIcon name="ChevronLeft" />}
            aria-label="Previous page"
            disabled={currentPage === 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            style={{ marginRight: 8 }}
          />
          <Text size={200}>
            {currentPage} of {totalPages}
          </Text>
          <Button
            appearance="subtle"
            icon={<FluentIcon name="ChevronRight" />}
            aria-label="Next page"
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
