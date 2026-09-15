import test, { describe } from "node:test";
import assert from "node:assert/strict";

import {
  applyBaseModelSelection,
  buildBaseModelOptionKey,
  buildModelCatalogEndpoint,
  normalizeBaseModelOptions,
  resolveBaseModelId,
} from "./BaseModelDropdownHelper.js";
import {
  buildCatalogDeletionEndpoint,
  catalogMetadataEntries,
  formatCatalogDate,
  hasCatalogCapability,
  readModelCatalog,
} from "./ModelCatalogHelper.js";
import {
  buildInferenceCatalogEndpoint,
  createCatalogInferenceSubmission,
  getCatalogInferenceReadiness,
  getCatalogRunProvenance,
  getLayerInferenceReadiness,
  getModelCancellationLabel,
  isInferenceOnlyModel,
  refreshCatalogInferenceModels,
} from "./CatalogInferenceHelper.js";
import { fetchModelCatalog } from "./CreateEditModelTrainingHelper.js";

test("builds a catalog query with event types and imagery source", () => {
  const endpoint = buildModelCatalogEndpoint(
    { sourceTypePostEvent: "Planet" },
    ["Hurricane", "Flood"]
  );

  assert.equal(
    endpoint,
    "GetModelCatalog?capability=training&eventTypes=Hurricane%2CFlood&imagerySource=Planet"
  );
});

test("omits absent catalog filters instead of stringifying them", () => {
  assert.equal(buildModelCatalogEndpoint({}, undefined), "GetModelCatalog?capability=training");
  assert.equal(
    buildModelCatalogEndpoint(
      { sourceTypePostEvent: "Planet" },
      undefined
    ),
    "GetModelCatalog?capability=training&imagerySource=Planet"
  );
});

test("encodes catalog filter values", () => {
  assert.equal(
    buildModelCatalogEndpoint(
      { sourceTypePostEvent: "World View" },
      ["Severe Storm"]
    ),
    "GetModelCatalog?capability=training&eventTypes=Severe+Storm&imagerySource=World+View"
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

describe("Catalog inference", () => {
  test("catalog distinguishes an empty response from malformed envelopes and records", () => {
    assert.deepEqual(readModelCatalog({ modelCatalog: [] }), []);
    for (const response of [
      null, {}, [], { modelCatalog: null }, { modelCatalog: {} },
      { modelCatalog: [null] }, { modelCatalog: [{ modelId: "missing-name" }] },
      { modelCatalog: [{ baseModelName: " " }] },
      { modelCatalog: [{ baseModelName: "duplicate" }, { baseModelName: "duplicate" }] },
    ]) {
      assert.throws(() => readModelCatalog(response), /Malformed model catalog/);
    }
  });

  test("catalog preserves external entries, nullable metadata, and the original document", () => {
    const external = Object.freeze({ baseModelName: "DINOv3", modelId: null, cataloguedDate: null, additionalInfo: null });
    const response = Object.freeze({ modelCatalog: Object.freeze([external]) });
    assert.equal(readModelCatalog(response), response.modelCatalog);
    assert.equal(formatCatalogDate(null), "--");
    assert.equal(formatCatalogDate({}), "--");
    assert.equal(formatCatalogDate("invalid"), "--");
    assert.equal(formatCatalogDate("2026-09-09T10:11:12Z"), "2026-09-09 10:11:12");
    assert.deepEqual(catalogMetadataEntries(null), []);
    assert.deepEqual(catalogMetadataEntries({}), []);
    assert.deepEqual(catalogMetadataEntries({ source: null }), [["source", null]]);
    assert.deepEqual(catalogMetadataEntries("External catalog"), [["Metadata", "External catalog"]]);
  });

  test("catalog removal uses the unique encoded name rather than a nullable modelId", () => {
    const endpoint = buildCatalogDeletionEndpoint({ baseModelName: "DINOv3 / RGB&v1", modelId: null });
    const params = new URLSearchParams(endpoint.split("?")[1]);
    assert.equal(params.get("baseModelName"), "DINOv3 / RGB&v1");
    assert.equal(params.has("modelId"), false);
  });

  test("legacy capabilities retain training while explicit inference-only entries do not", () => {
    assert.equal(hasCatalogCapability({}, "training"), true);
    assert.equal(hasCatalogCapability({ capabilities: null }, "training"), true);
    assert.equal(hasCatalogCapability({ capabilities: ["inference"] }, "training"), false);
    assert.equal(hasCatalogCapability({ capabilities: ["training", "inference"] }, "training"), true);
    assert.equal(hasCatalogCapability({ capabilities: "training" }, "training"), false);
  });

  test("training fetch requests capability=training and defensively filters infer-only entries", async () => {
    const models = Object.freeze([
      Object.freeze({ baseModelName: "Legacy HASTE", checkpointFilePath: "legacy.pt" }),
      Object.freeze({ baseModelName: "DINOv3", capabilities: ["inference"] }),
      Object.freeze({ baseModelName: "HASTE", capabilities: ["training", "inference"] }),
    ]);
    const options = await fetchModelCatalog({}, [], async (endpoint) => {
      assert.equal(endpoint, "GetModelCatalog?capability=training");
      return { modelCatalog: models };
    });
    assert.deepEqual(options.map((option) => option.text), ["Legacy HASTE", "HASTE"]);
    assert.equal(models.length, 3);
  });

  test("training fetch propagates service and malformed response errors instead of empty options", async () => {
    const failure = new Error("Catalog unavailable (503)");
    await assert.rejects(fetchModelCatalog({}, [], async () => { throw failure; }), (error) => error === failure);
    await assert.rejects(fetchModelCatalog({}, [], async () => ({})), /Malformed model catalog/);
    assert.deepEqual(await fetchModelCatalog({}, [], async () => ({ modelCatalog: [] })), []);
  });

  const preparedLayer = {
    workflowType: "standard", status: "Processed", postEventProcessedImageryUrl: "fixture-rgb.tif",
    buildingFootprintsUrl: "fixture-buildings.gpkg", labelProjectCount: 0,
  };

  test("standard inference needs prepared post-event imagery and cached footprints, not labels", () => {
    assert.equal(getLayerInferenceReadiness(preparedLayer).ready, true);
    assert.equal(getLayerInferenceReadiness({ ...preparedLayer, workflowType: null }).ready, true);
    assert.equal(getLayerInferenceReadiness({ ...preparedLayer, postEventProcessedImageryUrl: null, postEventMosaicCogImageryUrl: "raw.tif" }).ready, true);
    assert.equal(getLayerInferenceReadiness({ ...preparedLayer, workflowType: "building" }).ready, false);
    assert.equal(getLayerInferenceReadiness({ ...preparedLayer, workflowType: "unknown" }).ready, false);
    assert.match(getLayerInferenceReadiness({ ...preparedLayer, status: "InProgress" }).detail, /Prepare post-event/);
    assert.equal(getLayerInferenceReadiness({ ...preparedLayer, postEventProcessedImageryUrl: null }).ready, false);
    assert.match(getLayerInferenceReadiness({ ...preparedLayer, buildingFootprintsUrl: null }).detail, /footprints/);
    assert.equal(getLayerInferenceReadiness(null).ready, false);
  });

  test("inference catalog query is layer-aware without provider or event-name compatibility guesses", () => {
    const endpoint = buildInferenceCatalogEndpoint("project-fixture", "layer-fixture");
    assert.equal(endpoint, "GetModelCatalog?capability=inference&projectId=project-fixture&imageLayerId=layer-fixture");
  });

  test("inference accepts ready DINOv3 and legacy HASTE recipes with or without modelId", () => {
    for (const model of [
      { baseModelName: "DINOv3", capabilities: ["inference"], inferenceReady: true },
      { baseModelName: "HASTE", modelId: "source", inferenceReady: true },
      { baseModelName: "External HASTE", inferenceReady: true, capabilities: ["training", "inference"] },
    ]) {
      assert.equal(getCatalogInferenceReadiness(model).ready, true);
    }
  });

  test("inference fails closed on missing, contradictory, or incompatible readiness and exposes reasons", () => {
    assert.equal(getCatalogInferenceReadiness(null).ready, false);
    assert.equal(getCatalogInferenceReadiness({ capabilities: ["inference"] }).ready, false);
    assert.equal(getCatalogInferenceReadiness({ capabilities: ["training"], inferenceReady: true }).ready, false);
    assert.equal(getCatalogInferenceReadiness({ capabilities: ["inference"], inferenceReady: true, inferenceReadiness: { ready: false } }).ready, false);
    const incompatible = getCatalogInferenceReadiness({
      capabilities: ["inference"], inferenceReady: false,
      inferenceReadiness: { ready: false, reason: "channel_mismatch", detail: "Requires RGB post-event imagery." },
    });
    assert.equal(incompatible.ready, false);
    assert.match(incompatible.detail, /channel_mismatch.*Requires RGB/);
    assert.match(getCatalogInferenceReadiness({
      inferenceReady: false, inferenceReadiness: { reason: "missing_recipe" },
    }).detail, /missing_recipe/);
  });

  const request = {
    projectId: "project-fixture", imageLayerId: "layer-fixture", baseModelName: "DINOv3", name: "Run A",
  };
  const acceptedRun = { modelId: "new-model-fixture", modelType: "pretrained", name: "Run A", inferenceStatus: "Queued" };

  test("accepted inference sends only identifiers and optional name, never a recipe or checkpoint", async () => {
    const submission = createCatalogInferenceSubmission(() => "request-uuid");
    const result = await submission.submit({
      ...request, name: " Run A ", checkpointUrl: "not-allowed", config: {}, script: "not-allowed",
    }, async (endpoint, body) => {
      assert.equal(endpoint, "PutRunCatalogInferenceQueueMessage");
      assert.deepEqual(body, { ...request, clientRequestId: "request-uuid" });
      return acceptedRun;
    });
    assert.equal(result, acceptedRun);
    assert.equal(result.inferenceStatus, "Queued");
  });

  test("blank optional run names are omitted", async () => {
    await createCatalogInferenceSubmission(() => "request-uuid").submit({ ...request, name: "   " }, async (_, body) => {
      assert.equal("name" in body, false);
      return acceptedRun;
    });
  });

  test("ambiguous network failures retry the unchanged selection/name with the same UUID", async () => {
    let generated = 0;
    const submission = createCatalogInferenceSubmission(() => `uuid-${++generated}`);
    const bodies = [];
    const put = async (_, body) => { bodies.push(body); throw new Error("Connection lost"); };
    await assert.rejects(submission.submit(request, put), /Connection lost/);
    await assert.rejects(submission.submit({ ...request, name: " Run A " }, put), /Connection lost/);
    assert.deepEqual(bodies[0], bodies[1]);
    assert.equal(generated, 1);
  });

  test("a changed selection or name gets a new UUID after a failed attempt", async () => {
    let generated = 0;
    const submission = createCatalogInferenceSubmission(() => `uuid-${++generated}`);
    const bodies = [];
    const put = async (_, body) => { bodies.push(body); throw new Error("Unavailable"); };
    await assert.rejects(submission.submit(request, put));
    await assert.rejects(submission.submit({ ...request, name: "Run B" }, put));
    await assert.rejects(submission.submit({ ...request, name: "Run B", baseModelName: "HASTE" }, put));
    assert.deepEqual(bodies.map((body) => body.clientRequestId), ["uuid-1", "uuid-2", "uuid-3"]);
  });

  test("each newly opened intentional run gets a new UUID even with the same selection/name", async () => {
    let generated = 0;
    const createId = () => `uuid-${++generated}`;
    const bodies = [];
    const put = async (_, body) => { bodies.push(body); return acceptedRun; };
    await createCatalogInferenceSubmission(createId).submit(request, put);
    await createCatalogInferenceSubmission(createId).submit(request, put);
    assert.notEqual(bodies[0].clientRequestId, bodies[1].clientRequestId);
  });

  test("rapid duplicate submissions are locked before an asynchronous response", async () => {
    const submission = createCatalogInferenceSubmission(() => "request-uuid");
    let resolve;
    let calls = 0;
    const put = () => { calls++; return new Promise((done) => { resolve = done; }); };
    const first = submission.submit(request, put);
    assert.equal(await submission.submit(request, put), null);
    assert.equal(calls, 1);
    resolve(acceptedRun);
    assert.equal(await first, acceptedRun);
  });

  test("409 conflicts and malformed acceptances are errors, release the lock, and retain retry identity", async () => {
    for (const invalid of [409, undefined, {}, { modelId: "wrong-type", modelType: "training" }]) {
      let generated = 0;
      const submission = createCatalogInferenceSubmission(() => `uuid-${++generated}`);
      await assert.rejects(submission.submit(request, async () => invalid), invalid === 409 ? /409/ : /invalid inference acceptance/);
      assert.equal(await submission.submit(request, async () => acceptedRun), acceptedRun);
      assert.equal(generated, 1);
    }
  });

  test("refresh failures after acceptance cannot resubmit or overwrite the accepted model", async () => {
    const submission = createCatalogInferenceSubmission(() => "request-uuid");
    let calls = 0;
    const put = async () => { calls++; return acceptedRun; };
    await submission.submit(request, put);
    await assert.rejects(refreshCatalogInferenceModels(async (showLoading) => {
      assert.equal(showLoading, false);
      return false;
    }), /Unable to refresh model rows/);
    await assert.rejects(refreshCatalogInferenceModels(async () => {
      throw new Error("Refresh failed");
    }), /Refresh failed/);
    await refreshCatalogInferenceModels(async () => true);
    await refreshCatalogInferenceModels(async () => undefined);
    // The component retries only refreshing rows once acceptance is known.
    assert.equal(await submission.submit(request, put), acceptedRun);
    assert.equal(calls, 1);
  });

  test("model presentation distinguishes inference-only runs from training and embeddings", () => {
    assert.equal(isInferenceOnlyModel(acceptedRun), true);
    assert.equal(isInferenceOnlyModel({ inferenceStatus: "Queued" }), false);
    assert.equal(isInferenceOnlyModel({ modelType: "embedding" }), false);
    assert.equal(isInferenceOnlyModel(null), false);
  });

  test("the concrete queued run contract needs no fabricated training status or training job", async () => {
    const model = Object.freeze({
      modelId: "created-model", modelType: "pretrained",
      name: "DINOv3-run", catalogModelName: "DINOv3",
      pretrainedInference: Object.freeze({ adapter: "dinov3_upernet" }),
      inferenceRequestId: "request-uuid",
      inferenceStatus: "Queued", inferenceJobs: [],
      status: null, trainingJob: null,
    });
    const submission = createCatalogInferenceSubmission(() => "request-uuid");

    assert.equal(await submission.submit(request, async () => model), model);
    assert.equal(model.status, null);
    assert.equal(model.trainingJob, null);
    assert.equal(getModelCancellationLabel(model), "Cancel Inference");
    assert.deepEqual(getCatalogRunProvenance(model), {
      catalogName: "DINOv3", adapter: "dinov3_upernet", requestId: "request-uuid",
    });
  });

  test("queued and running pretrained cancellation depends only on inference state", () => {
    for (const inferenceStatus of ["Queued", "InProgress"]) {
      assert.equal(getModelCancellationLabel({ modelType: "pretrained", inferenceStatus }), "Cancel Inference");
    }
    for (const inferenceStatus of [undefined, null, "Cancelled", "Failed", "Processed"]) {
      assert.equal(getModelCancellationLabel({
        modelType: "pretrained", inferenceStatus, status: "Queued",
      }), null);
    }
    assert.equal(getModelCancellationLabel({ status: "InProgress" }), "Cancel Training");
    assert.equal(getModelCancellationLabel({ status: "Processed", inferenceStatus: "Queued" }), "Cancel Inference");
    assert.equal(getModelCancellationLabel(null), null);
  });

  test("optional provenance remains safe for sparse runs without leaking training metadata", () => {
    assert.deepEqual(getCatalogRunProvenance({
      modelType: "pretrained", catalogModelName: null,
      pretrainedInference: null, inferenceRequestId: null,
    }), { catalogName: "Unknown catalog model", adapter: "", requestId: "" });
    assert.equal(getCatalogRunProvenance({ modelType: "trained" }), null);
    assert.equal(getCatalogRunProvenance(null), null);
  });
});
