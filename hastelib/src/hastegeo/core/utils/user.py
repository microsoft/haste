from typing import NamedTuple

import requests
from azure.communication.email import EmailClient
from azure.identity import DefaultAzureCredential
from azure.mgmt.web import WebSiteManagementClient
from email_validator import EmailNotValidError, validate_email
from hastegeo.core.config import Config, InviteConfig
from hastegeo.core.models.users import Invite, Invites


class EmailSendResponse(NamedTuple):
    email_id: str
    sent: bool
    error: str | None


class CreateInvitationResponse(NamedTuple):
    email_id: str
    invitation_link: str
    error: str | None


class InvitationManager:
    def __init__(
        self,
        emails: str | list[str],
        roles: list[str] = None,
        invite_config: InviteConfig = None,
        invite_expire_hours: int = 168,  # 7 days by default
        delete_existing: bool = False,
    ):
        """
        Initialize the InvitationManager with email addresses, user roles, and invitation expiration.

        Args:
            emails (list[str]): List of email addresses to invite.
            roles (list[str]): List of roles to assign to invited users.
            invite_expire_hours (int, optional): Number of hours before the invitation expires. Defaults to 1.
        Raises:
            EnvironmentError: If required environment variables are missing.
        """
        if isinstance(emails, str):
            self.emails = [emails]
        else:
            self.emails = emails
        self.invite_config = invite_config or Config().INVITE
        self.roles = roles or self.invite_config.DEFAULT_USER_ROLES
        self.invite_expire_hours = invite_expire_hours
        self.delete_existing = delete_existing
        self.user_manager = (
            UserManager(self.invite_config) if delete_existing else None
        )

        if not all(
            [
                self.invite_config.STATIC_APP_SUBSCRIPTION_ID,
                self.invite_config.STATIC_APP_RESOURCE_GROUP,
                self.invite_config.STATIC_APP_NAME,
                self.invite_config.STATIC_APP_DOMAIN,
                self.invite_config.EMAIL_CONNECTION_STRING,
                self.invite_config.EMAIL_SENDER,
            ]
        ):
            raise EnvironmentError(
                "Missing required environment variables for invitation creation."
            )
        self.email_client = EmailClient.from_connection_string(
            self.invite_config.EMAIL_CONNECTION_STRING
        )

    def validate_emails(self) -> tuple[list[str], list[str]]:
        """
        Validate the list of email addresses using email_validator.

        Returns:
            tuple[list[str], list[str]]: A tuple containing a list of valid emails and a list of invalid emails.
        """
        valid_emails = []
        invalid_emails = []
        for email in self.emails:
            try:
                valid = validate_email(email, check_deliverability=True)
                valid_emails.append(valid.normalized)
            except EmailNotValidError:
                invalid_emails.append(email)
        return valid_emails, invalid_emails

    def send_invitations(self) -> Invites:
        """
        Validates emails, creates invitations, sends invitation emails, and returns the results.

        For each email:
          - If invalid, adds an Invite with error.
          - If valid, attempts to create an invitation link via Azure Static Web Apps API.
              - If invitation creation fails, adds an Invite with error.
              - If invitation creation succeeds, sends an email with the link and records the send status.

        Returns:
            Invites: An Invites object containing Invite objects for all processed emails, with status and errors.
        """
        valids, invalids = self.validate_emails()

        invite_objs = [
            Invite(
                email_id=e,
                invitation_link="",
                email_sent=False,
                error="Invalid email address",
            )
            for e in invalids
        ]

        for email in valids:
            invite_resp = self.create_invitation(email)
            if invite_resp.invitation_link:
                email_result = self.send_email(
                    invite_resp.email_id, invite_resp.invitation_link
                )
                invite_objs.append(
                    Invite(
                        email_id=email,
                        roles=self.roles if email_result.sent else [],
                        invitation_link=invite_resp.invitation_link,
                        email_sent=email_result.sent,
                        error="" if email_result.sent else email_result.error,
                    )
                )
                if (
                    email_result.sent
                    and self.delete_existing
                    and self.user_manager
                ):
                    self.user_manager.delete_user_by_email(email)
            else:
                invite_objs.append(
                    Invite(
                        email_id=email,
                        invitation_link="",
                        email_sent=False,
                        error=invite_resp.error,
                    )
                )
        return Invites(results=invite_objs)

    def create_invitation(self, email: str) -> dict:
        """
        Create an invitation for a single email address using Azure Static Web Apps REST API.

        Args:
            email (str): The email address to invite.

        Returns:
            dict: Dictionary with 'success' and 'error' keys containing invitation result or error details.
        """
        credential = DefaultAzureCredential()
        token = credential.get_token(
            "https://management.azure.com/.default"
        ).token

        url = (
            f"https://management.azure.com/subscriptions/"
            f"{self.invite_config.STATIC_APP_SUBSCRIPTION_ID}/resourceGroups/"
            f"{self.invite_config.STATIC_APP_RESOURCE_GROUP}/providers/Microsoft.Web/staticSites/"
            f"{self.invite_config.STATIC_APP_NAME}/createUserInvitation"
            f"?api-version=2024-11-01"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "properties": {
                "domain": self.invite_config.STATIC_APP_DOMAIN,
                "provider": "aad",
                "userDetails": email,
                "roles": ",".join(
                    self.roles
                ),  # Must be a comma-separated string if multiple roles are needed
                "numHoursToExpiration": self.invite_expire_hours,
            }
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            result = response.json()
            return CreateInvitationResponse(
                email_id=email,
                invitation_link=result.get("properties", {}).get(
                    "invitationUrl"
                ),
                error=None,
            )
        else:
            return CreateInvitationResponse(
                email_id=email,
                invitation_link="",
                error=response.text,
            )

    def send_email(self, recipient_email: str, link: str) -> str:
        # Build the email message as a dictionary
        message = {
            "senderAddress": self.invite_config.EMAIL_SENDER,
            "recipients": {
                "to": [
                    {
                        "address": recipient_email,
                        # "displayName": "Recipient"
                    }
                ]
            },
            "content": {
                "subject": "HASTE Invitation Link",
                "plainText": f"Please use the following link to access the HASTE application: {link}",
                "html": f"<p>Please use the following link to access the HASTE application: <a href='{link}'>{link}</a></p>",
            },
        }

        # Send the email
        try:
            poller = self.email_client.begin_send(message)
            result = poller.result()
            if result["status"].lower() == "succeeded":
                return EmailSendResponse(
                    email_id=recipient_email, sent=True, error=None
                )
            else:
                return EmailSendResponse(
                    email_id=recipient_email,
                    sent=False,
                    error=result.get("error"),
                )

        except Exception as e:
            return EmailSendResponse(
                email_id=recipient_email, sent=False, error=str(e)
            )


class UserManager:
    """
    Manages user operations for Azure Static Web Apps including listing, deleting, and updating users.
    """

    def __init__(self, invite_config: InviteConfig = None):
        """
        Initialize the UserManager with configuration.

        Args:
            invite_config (InviteConfig): Configuration for Static Web App connection
        """
        self.invite_config = invite_config or Config().INVITE
        self.credential = DefaultAzureCredential()
        self.web_client = WebSiteManagementClient(
            self.credential, self.invite_config.STATIC_APP_SUBSCRIPTION_ID
        )

    def list_users(self) -> list:
        """
        List all users in the Azure Static Web App.

        Returns:
            list: List of users from the Static Web App
        """
        return list(
            self.web_client.static_sites.list_static_site_users(
                resource_group_name=self.invite_config.STATIC_APP_RESOURCE_GROUP,
                name=self.invite_config.STATIC_APP_NAME,
                authprovider="all",
            )
        )

    def delete_user(self, user_id: str, auth_provider: str = "aad") -> bool:
        """
        Delete a user from the Azure Static Web App.

        Args:
            user_id (str): The ID of the user to delete
            auth_provider (str): The authentication provider (default: "aad")

        Returns:
            bool: True if deletion was successful

        Raises:
            Exception: If deletion fails
        """
        try:
            self.web_client.static_sites.delete_static_site_user(
                resource_group_name=self.invite_config.STATIC_APP_RESOURCE_GROUP,
                name=self.invite_config.STATIC_APP_NAME,
                authprovider=auth_provider,
                userid=user_id,
            )
            return True
        except Exception as e:
            # HTTP 204 "No Content" is the expected success response for DELETE operations
            if "No Content" in str(e) or "204" in str(e):
                return True
            raise RuntimeError(f"Failed to delete user {user_id}: {str(e)}")

    def find_user_by_email(self, email: str) -> dict | None:
        """
        Find a user by their email address.

        Args:
            email (str): Email address to search for

        Returns:
            dict | None: User object if found, None otherwise
        """
        users = self.list_users()
        for user in users:
            # Different auth providers may store email in different fields
            user_email = (
                getattr(user, "user_details", None)
                or getattr(user, "email", None)
                or getattr(user, "display_name", None)
            )
            if user_email and user_email.lower() == email.lower().strip():
                return user
        return None

    def delete_user_by_email(
        self, email: str, auth_provider: str = "aad"
    ) -> bool:
        """
        Delete a user by their email address.

        Args:
            email (str): Email address of user to delete
            auth_provider (str): The authentication provider (default: "aad")

        Returns:
            bool: True if deletion was successful

        Raises:
            Exception: If user not found or deletion fails
        """
        user = self.find_user_by_email(email)
        if not user:
            return True

        user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
        if not user_id:
            raise Exception(f"Could not determine user ID for {email}")
        auth_provider = (
            getattr(user, "provider", auth_provider) or auth_provider
        )

        return self.delete_user(user_id, auth_provider)
