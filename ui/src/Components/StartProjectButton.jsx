// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";

import CreateEditProjectModal from "./CreateEditProjectModal";
import proptypes from "prop-types";

const StartProjectButton = ({ setModalComponent, id }) => {
  StartProjectButton.propTypes = {
    setModalComponent: proptypes.func.isRequired,
    id: proptypes.string.isRequired,
  };

  return (
    <>
      <Button
        id={id}
        appearance="transparent"
        icon={<FluentIcon name="FabricNewFolder" />}
        className="start-project-btn"
        style={{ fontSize: 23, fontWeight: "500" }}
        onClick={() =>
          setModalComponent(
            <CreateEditProjectModal onClose={() => setModalComponent(null)} />
          )
        }
      >
        Start a Project
      </Button>
    </>
  );
};

export default StartProjectButton;
