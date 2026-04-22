# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from azure.identity import DefaultAzureCredential  # type: ignore
from azure.storage.queue import QueueServiceClient  # type: ignore


class AzureQueueHandler:
    def __init__(self, connection_string, queue_name, account_url):
        if connection_string:
            self.queue_service_client = (
                QueueServiceClient.from_connection_string(connection_string)
            )
        else:
            credential = DefaultAzureCredential()
            self.queue_service_client = QueueServiceClient(
                account_url=account_url, credential=credential
            )
        self.queue_client = self.queue_service_client.get_queue_client(
            queue_name
        )

        # Check if the queue exists, if not, create it
        try:
            self.queue_client.get_queue_properties()
        except Exception:
            self.queue_client.create_queue()

    def put_message(self, message, visibility_timeout=30):
        self.queue_client.send_message(
            message, visibility_timeout=visibility_timeout
        )

    def get_messages(self, max_messages=1):
        messages = self.queue_client.receive_messages(
            max_messages=max_messages
        )
        return [msg.content for msg in messages]

    def get_message_by_id(self, message_id, pop_receipt=None):
        message = self.queue_client.peek_message(message_id, pop_receipt)
        return message.content if message else None

    def delete_message(self, message_id, pop_receipt=None):
        self.queue_client.delete_message(message_id, pop_receipt)
