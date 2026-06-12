// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  PrimaryButton,
  TextField,
  Link,
  FontIcon,
  DefaultButton,
} from "@fluentui/react";

import { useNavigate } from "react-router-dom";
import { limitTextLength } from "../../util/conversion";
import { safeHref } from "../../util/validation";

import proptypes from "prop-types";

const SectionHeader = ({ properties, searchText, setSearchText, setCurrentPage }) => {
  SectionHeader.propTypes = {
    properties: proptypes.object.isRequired,
    searchText: proptypes.string,
    setSearchText: proptypes.func,
    setCurrentPage: proptypes.func,
  };

  const navigate = useNavigate();

  return (
    <div 
      className="container-fluid section-header"
    >
      <div className="container">
        <div className="row m-0 p-0 pt-5 pb-5 d-flex flex-column flex-md-row">
          {/* Breadcrumb */}
          <div className="col-auto flex-grow-1 p-0 header-breadcrumb">
            <div className="d-flex align-items-top">
              <FontIcon
                iconName={properties.iconName}
                className="me-2 section-header-icon"
              />
              <h5>
                {properties.path.map((item, index) => (
                  <span key={index}>
                    {item.link === "" ? (
                      limitTextLength(item.name, 25, 90)
                    ) : (
                      <Link className="section-header-breadcrumb" onClick={() => navigate(item.link)} id={item.id} >{limitTextLength(item.name, 20, 90)}</Link>
                    )}
                    {index < properties.path.length - 1 && (
                      <span>&nbsp;\&nbsp;</span>
                    )}
                  </span>
                ))}
              </h5>
            </div>
            {properties.links.map((link, index) =>
              link.type === "function" ? (
                <PrimaryButton
                  key={index}
                  onClick={link.link}
                  id={link.id}
                  className="mt-3"

                >
                  {link.name}
                </PrimaryButton>
              ) : (
                <Link
                  key={index}
                  href={safeHref(link.link)}
                  rel="noopener noreferrer"
                  className="me-3 pe-3 section-header-link"
                >
                  {link.name}
                </Link>
              )
            )}
          </div>

          {/* Add image layer button and filters */}
          {properties.filter && (
            <div className="col-auto p-0 mt-4 mt-lg-0 d-flex align-items-center">
              <div className="col-12 d-flex flex-column flex-lg-row justify-content-end" >
                <TextField
                  className="mb-1 mb-lg-0"
                  placeholder="Filter by any field"
                  aria-labelledby="sectionHeaderFilterLabel"
                  value={searchText}
                  onChange={(_, v) => {
                    setSearchText(v || "");
                    setCurrentPage(1);
                  }}
                />
                <DefaultButton disabled={!searchText} className="ms-lg-2" onClick={() => {
                  setSearchText("");
                  setCurrentPage(1);
                }}>Clear</DefaultButton>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SectionHeader;
