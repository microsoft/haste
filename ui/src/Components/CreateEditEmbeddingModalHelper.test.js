import test from "node:test";
import assert from "node:assert/strict";

import { createDefaultEmbeddingName } from "./CreateEditEmbeddingModalHelper.js";

const createdAt = new Date("2026-08-06T22:18:57.393Z");

test("creates a readable MOSAIKS name with dimensions and UTC time", () => {
  assert.equal(
    createDefaultEmbeddingName("mosaiks", "1024", createdAt),
    "mosaiks-1024-20260806-221857"
  );
});

test("uses the fixed DINOv2 output dimensions", () => {
  assert.equal(
    createDefaultEmbeddingName("dinov2_vits14", "1024", createdAt),
    "dinov2-vits14-384-20260806-221857"
  );
  assert.equal(
    createDefaultEmbeddingName("dinov2_vitb14", "1024", createdAt),
    "dinov2-vitb14-768-20260806-221857"
  );
});