// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Button,
  Dialog,
  DialogSurface,
  DialogBody,
  DialogActions,
  Input,
  Label,
} from "@fluentui/react-components";
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
          <Input
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

      <Dialog
        open={isModalOpen}
        onOpenChange={(e, data) => setIsModalOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <div className="d-flex flex-column w-100">
              <div className="d-flex align-items-center mb-3">
                <input
                  type="color"
                  aria-label="Select a color"
                  value={selectedColor}
                  onChange={(e) => setSelectedColor(e.target.value)}
                  style={{
                    width: "100%",
                    height: "40px",
                    border: "none",
                    cursor: "pointer",
                  }}
                />
                <div
                  className="ms-2"
                  style={{
                    width: "40px",
                    height: "40px",
                    flexShrink: 0,
                    border: "1px solid #ccc",
                    backgroundColor: selectedColor,
                  }}
                ></div>
              </div>
              <Input
                aria-label="Selected color hex value"
                value={selectedColor}
                readOnly
                maxLength={7}
              />
            </div>
            <DialogActions>
              <Button appearance="primary" onClick={handleColorSelection}>
                Select
              </Button>
              <Button onClick={() => setIsModalOpen(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
};

export default CustomColorPicker;
