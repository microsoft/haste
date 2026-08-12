// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const EMBEDDING_PROGRESS_PATTERN = /^Embedded \d+\/\d+ buildings$/;

function timestampValue(timestamp) {
  if (!timestamp) return null;
  const value = Date.parse(
    timestamp.replace(", ", "T").replace(" UTC", "Z")
  );
  return Number.isNaN(value) ? null : value;
}

function compareRows(left, right) {
  const leftTime = timestampValue(left.row.timestamp);
  const rightTime = timestampValue(right.row.timestamp);

  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
    return leftTime - rightTime;
  }
  if (leftTime !== null && rightTime === null) return 1;
  if (leftTime === null && rightTime !== null) return -1;
  return left.index - right.index;
}

export function normalizeStatusMessages(statusMessages) {
  const sorted = statusMessages
    .filter(
      ({ timestamp, message }) =>
        (timestamp && timestamp.trim()) || (message && message.trim())
    )
    .map((row, index) => ({ row, index }))
    .sort(compareRows);

  let latestEmbeddingProgress = null;
  const retained = [];

  for (const item of sorted) {
    if (EMBEDDING_PROGRESS_PATTERN.test(item.row.message.trim())) {
      latestEmbeddingProgress = item;
    } else {
      retained.push(item);
    }
  }

  if (latestEmbeddingProgress) retained.push(latestEmbeddingProgress);

  return retained.sort(compareRows).map(({ row }) => row);
}