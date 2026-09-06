import test from "node:test";
import assert from "node:assert/strict";

import {
  applyBaseModelSelection,
  buildBaseModelOptionKey,
  buildModelCatalogEndpoint,
  normalizeBaseModelOptions,
  resolveBaseModelId,
} from "./BaseModelDropdownHelper.js";

test("builds a catalog query with event types and imagery source", () => {
  const endpoint = buildModelCatalogEndpoint(
    { sourceTypePostEvent: "Planet" },
    ["Hurricane", "Flood"]
  );

  assert.equal(
    endpoint,
    "GetModelCatalog?eventTypes=Hurricane%2CFlood&imagerySource=Planet"
  );
});

test("omits absent catalog filters instead of stringifying them", () => {
  assert.equal(buildModelCatalogEndpoint({}, undefined), "GetModelCatalog");
  assert.equal(
    buildModelCatalogEndpoint(
      { sourceTypePostEvent: "Planet" },
      undefined
    ),
    "GetModelCatalog?imagerySource=Planet"
  );
});

test("encodes catalog filter values", () => {
  assert.equal(
    buildModelCatalogEndpoint(
      { sourceTypePostEvent: "World View" },
      ["Severe Storm"]
    ),
    "GetModelCatalog?eventTypes=Severe+Storm&imagerySource=World+View"
  );
});

test("keeps model ID and fallback name keys in disjoint namespaces", () => {
  const hasteModelKey = buildBaseModelOptionKey({
    modelId: "3516",
    baseModelName: "HASTE model",
  });
  const externalModelKey = buildBaseModelOptionKey({
    baseModelName: "3516",
  });

  assert.equal(hasteModelKey, "modelId:3516");
  assert.equal(externalModelKey, "baseModelName:3516");
  assert.notEqual(hasteModelKey, externalModelKey);
});

test("normalizes null descriptions and uses model names as fallback keys", () => {
  const options = normalizeBaseModelOptions([
    {
      value: {
        baseModelName: "External checkpoint A",
        description: null,
        checkpointFilePath: "models/external-a.pt",
      },
    },
    {
      value: {
        baseModelName: "External checkpoint B",
        description: null,
        checkpointFilePath: "models/external-b.pt",
      },
    },
  ]);

  assert.deepEqual(
    options.map((option) => option.key),
    [
      "baseModelName:External checkpoint A",
      "baseModelName:External checkpoint B",
    ]
  );
  assert.equal(options[0].description, "");
  assert.equal(options[1].description, "");
});

test("resolves an existing checkpoint URL to its catalog key", () => {
  const cataloguedModels = [
    {
      key: "modelId:model-1",
      value: {
        baseModelName: "Base model",
        checkpointFilePath: "models/base.pt",
      },
    },
  ];

  assert.equal(
    resolveBaseModelId(cataloguedModels, "models/base.pt"),
    "modelId:model-1"
  );
  assert.equal(resolveBaseModelId(cataloguedModels, "models/other.pt"), "");
});

test("applies the selected model id and checkpoint in one state update", () => {
  const currentState = { name: "Training model", baseModelIdError: "Required" };
  const selectedOption = {
    key: "modelId:model-1",
    checkpointFilePath: "models/base.pt",
  };

  assert.deepEqual(applyBaseModelSelection(currentState, selectedOption), {
    name: "Training model",
    baseModelId: "modelId:model-1",
    baseModelIdError: "",
    initialWeightsUrl: "models/base.pt",
  });
});
