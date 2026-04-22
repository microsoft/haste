// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  ColorPicker,
  TextField,
  Label,
  Modal,
  PrimaryButton,
  DefaultButton,
} from "@fluentui/react";
import { useEffect, useState } from "react";
import PropTypes from "prop-types";

const CustomColorPicker = ({
  labelText,
  color,
  category,
  field,
  onFormChange,
  disabled,
}) => {
  CustomColorPicker.propTypes = {
    labelText: PropTypes.string.isRequired,
    color: PropTypes.string.isRequired,
    category: PropTypes.string.isRequired,
    field: PropTypes.string.isRequired,
    onFormChange: PropTypes.func.isRequired,
    disabled: PropTypes.bool,
  };

  const [selectedColor, setSelectedColor] = useState(color);
  const [isModalOpen, setIsModalOpen] = useState(false);

  var isDisabled = false;
  if (disabled !== undefined) {
    isDisabled = disabled;
  }

  function handleColorSelection() {
    onFormChange(selectedColor, category, field);
    setIsModalOpen(false);
  }

  function handleModalOpen() {
    if (!isDisabled) {
      setIsModalOpen(true);
    }
  }

  useEffect(() => {
    setSelectedColor(color);
  }, []);

  return (
    <>
      <div onClick={() => handleModalOpen()} className="customColorPicker">
        <Label id={labelText} disabled={isDisabled}>
          {labelText}
        </Label>
        <div className="d-flex">
          <TextField
            aria-labelledby={labelText}
            className="me-1"
            style={{ width: "150px" }}
            value={color}
            readOnly
            disabled={isDisabled}
            maxLength={7}

          />
          <div
            style={{
              width: "32px",
              height: "32px",
              backgroundColor: color,
            }}
          ></div>
        </div>
      </div>

      <Modal isOpen={isModalOpen}>
        <div className="row p-0 m-0">
          <div className="col-12 p-2">
            <ColorPicker
              alphaType={"none"}
              showPreview={true}
              color={selectedColor}
              onChange={(e, color) => setSelectedColor(color.str)}
            />
            <div className="col-12 d-flex justify-content-end ps-3 pe-3 pb-3">
              <PrimaryButton
                className="mt-3 me-2"
                onClick={handleColorSelection}
              >
                Select
              </PrimaryButton>
              <DefaultButton
                className="mt-3"
                onClick={() => setIsModalOpen(false)}
              >
                Cancel
              </DefaultButton>
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
};

export default CustomColorPicker;
