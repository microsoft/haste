// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import PropTypes from "prop-types";
import { FluentIcon } from "../../util/icons";
import "../../assets/css/drawingToolbar.css";

const DrawingToolbar = ({ drawingManager, setDrawingManager, undo, redo }) => {
  DrawingToolbar.propTypes = {
    drawingManager: PropTypes.object.isRequired,
    setDrawingManager: PropTypes.func.isRequired,
    undo: PropTypes.func.isRequired,
    redo: PropTypes.func.isRequired,
  };

  const [activeMode, setActiveMode] = useState("none");

  const buttons = [
    {
      mode: "none",
      label: <FluentIcon name="HandsFree" />,
      disabled: false,
      title: "Pointer",
      id: "pointer",
    },
    {
      mode: "draw-polygon",
      label: <FluentIcon name="WebAppBuilderModule" />,
      disabled: false,
      title: "Draw Polygon",
      id: "draw-polygon",
    },
    {
      mode: "edit-geometry",
      label: <FluentIcon name="Edit" />,
      disabled: false,
      title: "Edit Geometry",
      id: "edit-geometry",
    },
    {
      label: <FluentIcon name="Undo" />,
      disabled: false,
      title: "Undo",
      id: "undo",
    },
    {
      label: <FluentIcon name="Redo" />,
      disabled: false,
      title: "Redo",
      id: "redo",
    },
    {
      mode: "draw-line",      
      label: <FluentIcon name="Cut" />,
      disabled: false,
      title: "Cut",
      id: "cut",
    },
    {
      mode: "erase-geometry",
      label: <FluentIcon name="Delete" />,
      disabled: false,
      title: "Erase Geometry",
      id: "erase-geometry",
    },
  ];

  const handleClick = (mode, isDisabled) => {
    if (isDisabled) return;
    if (!drawingManager) return;

    drawingManager.setOptions({ mode });
    setDrawingManager(drawingManager);
    setActiveMode(mode);
  };

  return (
    <div
      id="drawingToolbar"
      role="toolbar"
      aria-label="Drawing tools"
    >
      {buttons.map((btn) => {
        const classNames = ["drawing-button"];

        if (btn.id === "undo" || btn.id === "redo") {
          return (<button
            key={btn.id}
            onClick={() => {
              if (btn.id === "undo") {
                undo();
              } else {
                redo();
              }
            }}
            disabled={btn.disabled}
            title={btn.title}
            className={"drawing-button"}
            id={btn.id}
          >
            {btn.label}
          </button>);
        } else {

          if (activeMode === btn.mode) classNames.push("active");
          if (btn.disabled) classNames.push("disabled");

          return (
            <button
              key={btn.mode}
              onClick={() => handleClick(btn.mode, btn.disabled)}
              disabled={btn.disabled}
              title={btn.title}
              className={classNames.join(" ")}
              id={btn.id}
            >
              {btn.label}
            </button>
          );
        }
      })}

    </div>
  );
};

export default DrawingToolbar;
