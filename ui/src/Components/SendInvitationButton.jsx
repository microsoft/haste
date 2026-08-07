// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components

import { Button } from "@fluentui/react-components";

const SendInvitationButton = () => {


function handleSendInvitation(){
    alert("Invitation sent!");
}

  return (
    <Button
      appearance="primary"
      onClick={() => {
        handleSendInvitation();
      }}
    >
      Send Invitation
    </Button>
  );
};

export default SendInvitationButton;
