#! /bin/bash

# Helper script to bulk generate invitation links given a file called `emails.txt` containing one email per line, with empty line at the end of the file
# Update the variables below with your Azure subscription and resource group details
export SUBSCRIPTION_ID="<REPLACE_ME>"
export RESOURCE_GROUP="<REPLACE_ME>"
export STATIC_WEB_APP="<REPLACE_ME>"
export STATIC_WEB_APP_DOMAIN="<REPLACE_ME>"

while IFS= read -r USER_EMAIL; do
    echo "Creating invitation for $USER_EMAIL"
    RESPONSE=$(az rest --method POST \
        --uri "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/staticSites/$STATIC_WEB_APP/createUserInvitation?api-version=2024-04-01" \
        --body "{
            \"properties\": {
                \"domain\": \"$STATIC_WEB_APP_DOMAIN\",
                \"provider\": \"aad\",
                \"userDetails\": \"$USER_EMAIL\",
                \"roles\": \"contributors\",
                \"numHoursToExpiration\": 168
            }
        }")
    INVITATION_URL=$(echo "$RESPONSE" | jq -r '.properties.invitationUrl')
    echo "$USER_EMAIL, $INVITATION_URL"
done < emails.txt

