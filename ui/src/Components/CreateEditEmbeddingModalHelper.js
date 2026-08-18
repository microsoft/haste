// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const MODEL_NAME_PARTS = {
  mosaiks: { slug: "mosaiks" },
  dinov2_vits14: { slug: "dinov2-vits14", dimensions: "384" },
  dinov2_vitb14: { slug: "dinov2-vitb14", dimensions: "768" },
};

export function createDefaultEmbeddingName(
  embeddingModel,
  numFeatures,
  createdAt = new Date()
) {
  const model = MODEL_NAME_PARTS[embeddingModel] || {
    slug: String(embeddingModel || "embedding").replaceAll("_", "-"),
  };
  const dimensions =
    model.dimensions || String(numFeatures || "features");
  const timestamp = createdAt
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z")
    .replace("T", "-")
    .replace("Z", "");

  return `${model.slug}-${dimensions}-${timestamp}`;
}