// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components

import { PrimaryButton } from "@fluentui/react";

const SendInvitationButton = () => {


function handleSendInvitation(){
    alert("Invitation sent!");
}

  return (
    <PrimaryButton
      text="Send Invitation"
      onClick={() => {
        handleSendInvitation();
      }}
    />
  );
};

export default SendInvitationButton;
