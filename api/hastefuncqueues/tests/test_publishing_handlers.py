import json
import os
import unittest
from unittest.mock import Mock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-publishing-queue-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-publishing-queue-tests")

from api.hastefuncqueues import function_app  # noqa: E402

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
DATASET_ID = "3e8d5e90-f2fc-5412-9f97-a52c07815f0b"


def queue_message(operation: str = "publish") -> func.QueueMessage:
    return func.QueueMessage(
        id="message-id",
        body=json.dumps(
            {
                "projectId": PROJECT_ID,
                "datasetId": DATASET_ID,
                "operation": operation,
                "attempt": 1,
            }
        ),
    )


class TestPublishingQueueHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_publish_handler_decodes_and_delegates(self) -> None:
        processor = Mock()
        with patch.object(
            function_app, "PublishingProcessor", return_value=processor
        ):
            await function_app.GetPublishDatasetQueueMessage(queue_message())

        message = processor.run_step.call_args.args[0]
        self.assertEqual(str(message.projectId), PROJECT_ID)
        self.assertEqual(str(message.datasetId), DATASET_ID)
        self.assertEqual(message.operation.value, "publish")

    async def test_publish_handler_rejects_malformed_message(self) -> None:
        message = func.QueueMessage(id="message-id", body="not-json")

        with self.assertRaisesRegex(RuntimeError, "JSONDecodeError") as raised:
            await function_app.GetPublishDatasetQueueMessage(message)

        self.assertNotIn("not-json", str(raised.exception))

    async def test_publish_handler_redacts_processor_exception_message(
        self,
    ) -> None:
        processor = Mock()
        processor.run_step.side_effect = RuntimeError(
            "https://storage/blob?sig=secret"
        )
        with patch.object(
            function_app, "PublishingProcessor", return_value=processor
        ):
            with self.assertRaisesRegex(
                RuntimeError, "RuntimeError"
            ) as raised:
                await function_app.GetPublishDatasetQueueMessage(
                    queue_message()
                )

        self.assertNotIn("secret", str(raised.exception))

    async def test_poison_handler_delegates_current_operation(self) -> None:
        processor = Mock()
        with patch.object(
            function_app, "PublishingProcessor", return_value=processor
        ):
            await function_app.GetPublishDatasetPoisonQueueMessage(
                queue_message("unpublish")
            )

        message = processor.mark_poisoned.call_args.args[0]
        self.assertEqual(message.operation.value, "unpublish")

    async def test_poison_handler_ignores_removed_dataset(self) -> None:
        processor = Mock()
        processor.mark_poisoned.side_effect = FileNotFoundError(DATASET_ID)
        with patch.object(
            function_app, "PublishingProcessor", return_value=processor
        ):
            await function_app.GetPublishDatasetPoisonQueueMessage(
                queue_message()
            )

    async def test_timer_delegates_reconciliation(self) -> None:
        processor = Mock()
        processor.reconcile_stale.return_value = 2
        with patch.object(
            function_app, "PublishingProcessor", return_value=processor
        ):
            await function_app.ReconcilePublishingOperations(Mock())

        processor.reconcile_stale.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
