// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Nav, Dropdown, SelectableOptionMenuItemType} from "@fluentui/react";
import PropTypes from "prop-types";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const HelpDocsNav = ({ helpSections, selectedKey }) => {
  HelpDocsNav.propTypes = {
    helpSections: PropTypes.array.isRequired,
    selectedKey: PropTypes.string,
  };

  const [helpSectionsForComboBox, setHelpSectionsForComboBox] = useState([]);
  const navigate = useNavigate();

  const handleSelection = (option) => {
    if (option) {
      for (const section of helpSections[0].links) {
        if (section.links && section.links.length > 0) {
          for (const link of section.links) {
            if (link.key === option.key) {
              navigate(`/help-docs/${link.onClick()}`);
              return;
            }
          }
        }
      }
    }
  }


  useEffect(() => {
    if (helpSections !== null && helpSections.length > 0) {
      var tempSectionsForComboBox = [];
      helpSections[0].links.forEach((section) => {
        if (section.links && section.links.length > 0) {
          tempSectionsForComboBox.push({
            key: section.key,
            text: section.name,
            itemType: SelectableOptionMenuItemType.Header,
          });
          section.links.forEach((link) => {
            tempSectionsForComboBox.push({
              key: link.key,
              text: link.name,
            });
          });
        }
      });
      setHelpSectionsForComboBox(tempSectionsForComboBox);
    }

  }, []);


  return (

    <div
      className="col-12 col-lg-auto p-4 ps-2 pe-3 help-docs-nav-container"
    >
      <Nav
        className="help-docs-nav d-none d-lg-flex"
        groups={helpSections}
        selectedKey={null}
      />

      {helpSectionsForComboBox != null && helpSectionsForComboBox.length && (
        <Dropdown
          id="help-docs-nav-combobox"
          ariaLabel="ExpandSections"
          options={helpSectionsForComboBox}
          label="Help Docs Sections"
          onKeyUp={(e) => {
            if (e.key === "Enter") {
              handleSectionAddition();
            }
          }}
          onItemClick={(e, option) => {
            if (option) {
              handleSelection(option);
            }
          }}
          selectedKey={selectedKey !== null ? selectedKey : undefined}
          className="flex-grow-1 d-lg-none"
          onChange={(_, option) => handleSelection(option)}
          text=""
        />
      )}

    </div>
  );
};

export default HelpDocsNav;
