// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Button } from "@fluentui/react-components";
import PropTypes from "prop-types";
import { FluentIcon } from "../util/icons";

const NoResultsMessage = ({
  title,
  fallbackMessage = "No items match your filters.",
  searchText = "",
  onClear = null,
  clearLabel = "Clear search",
}) => {
  const normalizedSearch = (searchText || "").trim();
  const details = normalizedSearch
    ? `No matches for "${normalizedSearch}".`
    : fallbackMessage;

  return (
    <div className="pgrid-no-results" role="status" aria-live="polite">
      <FluentIcon name="Search" className="pgrid-no-results-icon" />
      <div className="pgrid-no-results-title">{title}</div>
      <div className="pgrid-no-results-text">{details}</div>
      {onClear && normalizedSearch.length > 0 && (
        <Button appearance="secondary" size="small" onClick={onClear}>
          {clearLabel}
        </Button>
      )}
    </div>
  );
};

NoResultsMessage.propTypes = {
  title: PropTypes.string.isRequired,
  fallbackMessage: PropTypes.string,
  searchText: PropTypes.string,
  onClear: PropTypes.func,
  clearLabel: PropTypes.string,
};

export default NoResultsMessage;