// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { ActionButton } from "@fluentui/react";

import CreateEditProjectModal from "./CreateEditProjectModal";
import proptypes from "prop-types";

const StartProjectButton = ({ setModalComponent, id }) => {
  StartProjectButton.propTypes = {
    setModalComponent: proptypes.func.isRequired,
    id: proptypes.string.isRequired,
  };

  return (
    <>
      <ActionButton
        id={id}
        iconProps={{
          iconName: "FabricNewFolder",
          styles: { root: { fontSize: 24, fontWeight: "500" } },
        }}
        styles={{
          root: { fontSize: 23, fontWeight: "500", color: "#0066b4" },
        }}
        onClick={() =>
          setModalComponent(
            <CreateEditProjectModal onClose={() => setModalComponent(null)} />
          )
        }
      >
        Start a Project
      </ActionButton>
    </>
  );
};

export default StartProjectButton;
