import test from "node:test";
import assert from "node:assert/strict";

import { normalizeStatusMessages } from "./statusMessages.js";

test("collapses embedding ticks and sorts all timestamped rows", () => {
  const progressRows = Array.from({ length: 1478 }, (_, index) => ({
    timestamp: "2026-08-06, 22:20:03 UTC",
    message: `Embedded ${index + 1}/112687 buildings`,
  }));
  const rows = [
    { timestamp: "2026-08-06, 22:19:52 UTC", message: "Embedding submitted" },
    {
      timestamp: "2026-08-06, 22:27:02 UTC",
      message: "Embedded 112686/112687 buildings (1 with no valid tokens kept as NaN)",
    },
    ...progressRows,
    { timestamp: "2026-08-06, 22:26:51 UTC", message: "Finalizing outputs" },
  ];

  const result = normalizeStatusMessages(rows);

  assert.equal(result.length, 4);
  assert.deepEqual(
    result.map(({ message }) => message),
    [
      "Embedding submitted",
      "Embedded 1478/112687 buildings",
      "Finalizing outputs",
      "Embedded 112686/112687 buildings (1 with no valid tokens kept as NaN)",
    ]
  );
});

test("preserves stable order for rows without timestamps", () => {
  const rows = [
    { timestamp: "", message: "Worker details" },
    { timestamp: "", message: "Retry details" },
  ];

  assert.deepEqual(normalizeStatusMessages(rows), rows);
});