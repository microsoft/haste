// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Checkbox, TextField, PrimaryButton } from "@fluentui/react";

import { useState, useEffect, useContext } from "react";
import { createComponentDefaultState } from "./AdminLabelingTollHelper";

import SectionHeader from "./Section/SectionHeader";
import CustomColorPicker from "./OtherComponents/ColorPicker";

import { AppContext } from "../AppContext";

const AdminLabelingTool = () => {
  const [componentState, setComponentState] = useState(null);
  const { setIsLoading } = useContext(AppContext);

  useEffect(() => {
    async function initComponent() {
      setIsLoading(true);
      setComponentState(await createComponentDefaultState());
      setIsLoading(false);
    }
    initComponent();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* Section Header Properties */

  const sectionHeaderProperties = {
    iconName: "UserEvent",
    path: [{ name: "Labeling Tool Settings", link: "" }],
    links: [
      {
        name: "Users",
        link: "/admin-users",
      },
      {
        name: "Source Types",
        link: "/admin-source-types",
      },
      {
        name: "Labeling Tool",
        link: "/admin-labeling-tool",
      },
    ],
    filter: false,
    filterText: "",
    filterButtonText: "",
    filterPlaceholder: "",
  };

  const onFormChange = (value, category, key) => {
    setComponentState((prevState) => ({
      ...prevState,
      [category]: {
        ...prevState[category],
        [key]: value,
      },
    }));
  };

  if (!componentState) {
    return null;
  }

  return (
    <>
      <div className="d-flex flex-column w-100 mb-5">
        <SectionHeader properties={sectionHeaderProperties} />

        <div className="container p-0">
          {/* Drawing Tools */}
          <div
            className="row m-0 p-0 pt-5 pb-4"
            style={{ borderBottom: "1px solid #CCCCCC" }}
          >
            <div className="col-12 pb-3">
              <h6>Drawing Tools</h6>
            </div>
            <div className="col-12 d-flex">
              <Checkbox
                label="Polygon"
                className="me-5"
                checked={componentState.drawingTools.polygon}
                onChange={(e) =>
                  onFormChange(e.target.checked, "drawingTools", "polygon")
                }
              />
              <Checkbox
                label="Rectangle"
                checked={componentState.drawingTools.rectangle}
                className="me-5"
                onChange={(e) =>
                  onFormChange(e.target.checked, "drawingTools", "rectangle")
                }
              />
              <Checkbox
                label="Circle"
                checked={componentState.drawingTools.circle}
                onChange={(e) =>
                  onFormChange(e.target.checked, "drawingTools", "circle")
                }
              />
            </div>
          </div>

          {/* Grid */}
          <div
            className="row m-0 p-0 pt-5 pb-4"
            style={{ borderBottom: "1px solid #CCCCCC" }}
          >
            <div className="col-12">
              <h6>Grid</h6>
            </div>
            <div className="col-12 d-flex">
              <div className="me-5">
                <CustomColorPicker
                  labelText={"Grid stroke color"}
                  color={componentState.grid.gridStrokeColor}
                  category={"grid"}
                  field={"gridStrokeColor"}
                  onFormChange={onFormChange}
                  disabled={false}
                />
              </div>
            </div>
          </div>

          {/* Label Colors */}
          <div className="row m-0 p-0 pt-5 pb-4">
            <div className="col-12">
              <h6>Label</h6>
            </div>
            <div className="col-12 d-flex"></div>
          </div>

          <div
            className="row m-0 p-0 pb-4"
            style={{ borderBottom: "1px solid #CCCCCC" }}
          >
            <div className="col-12 d-flex">
              {componentState.defaultPrimaryClasses.map((item, index) => (
                <div className="me-5" key={index}>
                  <CustomColorPicker
                    labelText={item.name}
                    color={item.color}
                    category={"label"}
                    field={"backgroundFillColor"}
                    onFormChange={onFormChange}
                    disabled={false}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Label Colors */}
          <div className="row m-0 p-0 pt-5 pb-4">
            <div className="col-12">
              <h6>Tile server settings</h6>
            </div>
            <div className="col-12 d-flex"></div>
          </div>

          <div
            className="row m-0 p-0 pb-4"
            style={{ borderBottom: "1px solid #CCCCCC" }}
          >
            <div className="col-12 d-flex">
              <TextField
                className="w-100"
                multiline
                value={componentState.tileServerSettings}
              />
            </div>
          </div>

          <div className="row m-0 p-0 pt-5">
            <div className="col-12 d-flex justify-content-end">
              <PrimaryButton text="Save" />
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AdminLabelingTool;
