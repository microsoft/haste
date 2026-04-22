Azure Function: hastefuncqueues

This Azure Function implements queue trigger functions for the HASTE project. 
It processes messages from Azure Storage Queues to handle various tasks related 
to image processing, model runs, inference, and statistics updates.

Queue Trigger Functions:
1. GetProcessImageLayerQueueMessage(msg: func.QueueMessage) -> None:
    - Triggered by a queue message to process image layers.

2. GetCreateModelRunQueueMessage(msg: func.QueueMessage) -> None:
    - Triggered by a queue message to create model runs.

3. GetRunInferenceQueueMessage(msg: func.QueueMessage) -> None:
    - Triggered by a queue message to run inference on models.

4. GetUpdateStatsMessage(msg: func.QueueMessage) -> None:
    - Triggered by a queue message to update statistics.

Each function is designed to handle specific tasks by processing the messages 
retrieved from the corresponding Azure Storage Queue.