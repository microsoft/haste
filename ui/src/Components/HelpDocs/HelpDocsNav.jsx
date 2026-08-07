// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Dropdown, Option } from "@fluentui/react-components";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";

const HelpDocsNav = ({ helpSections, selectedKey }) => {
  HelpDocsNav.propTypes = {
    helpSections: PropTypes.array.isRequired,
    selectedKey: PropTypes.string,
  };

  const navigate = useNavigate();

  const handleSelection = (optionKey) => {
    if (optionKey) {
      for (const section of helpSections[0].links) {
        if (section.links && section.links.length > 0) {
          for (const link of section.links) {
            if (link.key === optionKey) {
              navigate(`/help-docs/${link.onClick()}`);
              return;
            }
          }
        }
      }
    }
  };

  return (
    <div className="col-12 col-lg-auto p-4 ps-2 pe-3 help-docs-nav-container">
      {/* Desktop sidebar */}
      <div className="help-docs-nav d-none d-lg-flex flex-column">
        {helpSections[0].links.map((section) => (
          <div key={section.key} className="mb-3">
            <div className="fw-semibold mb-1">{section.name}</div>
            {section.links &&
              section.links.map((link) => (
                <div
                  key={link.key}
                  role="button"
                  tabIndex={0}
                  className={`help-docs-nav-link ${
                    link.key === selectedKey ? "help-docs-nav-link-active" : ""
                  }`}
                  onClick={() => navigate(`/help-docs/${link.onClick()}`)}
                  onKeyUp={(e) => {
                    if (e.key === "Enter") {
                      navigate(`/help-docs/${link.onClick()}`);
                    }
                  }}
                >
                  {link.name}
                </div>
              ))}
          </div>
        ))}
      </div>

      {/* Mobile dropdown */}
      <Dropdown
        id="help-docs-nav-combobox"
        aria-label="ExpandSections"
        placeholder="Help Docs Sections"
        className="flex-grow-1 d-lg-none"
        selectedOptions={selectedKey ? [selectedKey] : []}
        onOptionSelect={(e, data) => handleSelection(data.optionValue)}
      >
        {helpSections[0].links.map((section) =>
          section.links && section.links.length > 0 ? (
            <div key={section.key}>
              <Option value={section.key} disabled text={section.name}>
                {section.name}
              </Option>
              {section.links.map((link) => (
                <Option key={link.key} value={link.key} text={link.name}>
                  {link.name}
                </Option>
              ))}
            </div>
          ) : null
        )}
      </Dropdown>
    </div>
  );
};

export default HelpDocsNav;
