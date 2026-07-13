// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Azure Maps Interactive Labeler — PMTiles edition.
//
// Footprints are streamed from a PMTiles archive (built by the embedding
// workflow) via Azure Maps' addProtocol hook, so only the tiles in the
// current viewport are fetched — the labeler is no longer bottlenecked on
// up-front loading of every building. Per-building coloring is driven by
// feature-state on the internal Mapbox-GL map; per-building f_* feature
// vectors come from the rendered features (tippecanoe writes them into the
// tiles) so the in-browser model trains and predicts on whatever the user
// is currently looking at.
//
// A separate "Predict all buildings" button downloads the full embeddings
// GeoJSON once and batches the trained model across every footprint with
// a progress modal, then persists the predictions so the Validation and
// Assessment reports cover the whole layer.
//
// Implementation notes live in `AZURE_MAPS_INTERACTIVE_LABELER.md`.
import { useContext, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ActionButton,
  ChoiceGroup,
  DefaultButton,
  PrimaryButton,
  ProgressIndicator,
  Text,
  Toggle,
} from "@fluentui/react";
import { PMTiles, Protocol } from "pmtiles";
import { apiGet, apiPut, buildUrl } from "../../util/api";
import {
  getAzureMapsAuthOptions,
  isAzureMapsPlaceholder,
} from "../../util/azureMapsAuth";
import { toBrowserTitilerUrl } from "../../util/blobUrl";
import { AppContext } from "../../AppContext.jsx";
import { loadImagery } from "../LabelingTool/LabelingToolHelper.js";
import {
  CLASS_CLOUDY,
  CLASS_DAMAGED,
  CLASS_INTACT,
  OvRLogisticRegression,
  holdoutMetricsDamaged,
  isValidVector,
} from "./interactiveModel.js";
import { getGpu } from "./gpuLogreg.js";

// Register the pmtiles protocol once at module load. After this, any
// VectorTileSource configured with `url: "pmtiles://<url>"` will route
// through pmtiles' byte-range-aware reader. Atlas v3 exposes the Mapbox-GL
// style `addProtocol` hook (see AZURE_MAPS_INTERACTIVE_LABELER.md §2).
const _pmtilesProtocol = new Protocol();
if (typeof window !== "undefined" && window.atlas) {
  // The bound `.tile` member is what addProtocol expects. Re-registering the
  // same scheme is idempotent in atlas.
  window.atlas.addProtocol("pmtiles", _pmtilesProtocol.tile);
}

// Tippecanoe writes the buildings layer with `-l buildings`. The
// VectorTileSource references this layer name to draw the polygons.
const PMTILES_SOURCE_LAYER = "buildings";

// pmtiles.js reads an archive through a `Source` (getKey + getBytes). Its
// default FetchSource issues HTTP Range requests, but the Interactive
// Labeler is served behind an Azure Static Web App whose /api proxy does
// NOT honor byte serving: a ranged GET comes back as a full 200, so
// pmtiles throws "Server returned no content-length header or content-length
// exceeding request." We sidestep that by downloading the whole archive once
// (a plain full GET, which the SWA proxy handles fine — same as the HFTR
// sidecar) and satisfying every range read from that in-memory buffer.
// `getKey()` must equal the string used in the `pmtiles://<key>` source URL
// so Protocol.add()'s lookup matches.
class InMemoryPMTilesSource {
  constructor(key, arrayBuffer) {
    this._key = key;
    this._buf = arrayBuffer;
  }
  getKey() {
    return this._key;
  }
  async getBytes(offset, length) {
    // ArrayBuffer.slice clamps to the buffer end, which is what pmtiles
    // expects for the initial 16 KB header read on a smaller archive.
    return { data: this._buf.slice(offset, offset + length) };
  }
}

// Download an entire artifact through the same-origin API proxy as raw
// bytes. Used for the PMTiles archive so it can be read fully in memory
// (see InMemoryPMTilesSource) rather than via unsupported range requests.
async function fetchArtifactBuffer(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(
      `Failed to fetch PMTiles archive (HTTP ${resp.status}) at ${url}`
    );
  }
  return resp.arrayBuffer();
}

// Class colors (match index.html). Index = class number.
const CLASS_COLORS = ["#107C10", "#C50F1F", "#5B5FC7"]; // intact, damaged, cloudy
const UNLABELED_COLOR = "#BDBDBD";

// In-browser class -> validation-report vocabulary (Damaged/NotDamaged/Unknown).
const CLASS_TO_VALIDATION = {
  [CLASS_INTACT]: "NotDamaged",
  [CLASS_DAMAGED]: "Damaged",
  [CLASS_CLOUDY]: "Unknown",
};
const VALIDATION_TO_CLASS = {
  NotDamaged: CLASS_INTACT,
  Damaged: CLASS_DAMAGED,
  Unknown: CLASS_CLOUDY,
};

const CLASS_OPTIONS = [
  { key: String(CLASS_INTACT), text: "Intact" },
  { key: String(CLASS_DAMAGED), text: "Damaged" },
  { key: String(CLASS_CLOUDY), text: "Cloudy" },
];

const MIN_PER_CLASS = 3;
// Predict batch size for the "Predict all buildings" full-coverage pass.
// Large enough to amortize the OvRLogisticRegression.predict() per-call
// overhead, small enough to keep the progress bar feeling responsive.
const FULL_PREDICT_BATCH = 5000;

// AZURE_MAPS_INTERACTIVE_LABELER.md §4: atlas.Map has no public
// setFeatureState; the renderer underneath (a Mapbox-GL fork) does. Reach
// it via this duck-typed scan. Wrap callers in null-checks so we degrade
// gracefully if a future SDK update hides it differently.
function findGlMap(atlasMap) {
  const direct = [atlasMap.map, atlasMap._map, atlasMap.gl, atlasMap._gl];
  for (const c of direct) {
    if (c && typeof c.setFeatureState === "function") return c;
  }
  for (const k of Object.keys(atlasMap)) {
    const v = atlasMap[k];
    if (v && typeof v === "object" && typeof v.setFeatureState === "function") {
      return v;
    }
  }
  return null;
}

// Build the fillColor paint expression for a given feature-state key
// (either "label" or "pred"). Both modes use the same color ramp; we just
// swap which state we read.
function fillColorExpr(stateKey) {
  return [
    "case",
    ["==", ["feature-state", stateKey], CLASS_INTACT], CLASS_COLORS[CLASS_INTACT],
    ["==", ["feature-state", stateKey], CLASS_DAMAGED], CLASS_COLORS[CLASS_DAMAGED],
    ["==", ["feature-state", stateKey], CLASS_CLOUDY], CLASS_COLORS[CLASS_CLOUDY],
    UNLABELED_COLOR,
  ];
}

// Fill opacity for a labeled/predicted building. Unlabeled buildings (no
// matching feature-state for stateKey) get a fully transparent fill so only
// their outline shows.
const LABELED_FILL_OPACITY = 0.5;

// Build the fillOpacity paint expression for a given feature-state key,
// mirroring fillColorExpr so opacity tracks the same "label"/"pred" state.
function fillOpacityExpr(stateKey) {
  return [
    "case",
    ["==", ["feature-state", stateKey], CLASS_INTACT], LABELED_FILL_OPACITY,
    ["==", ["feature-state", stateKey], CLASS_DAMAGED], LABELED_FILL_OPACITY,
    ["==", ["feature-state", stateKey], CLASS_CLOUDY], LABELED_FILL_OPACITY,
    0,
  ];
}

// Binary HFTR sidecar:
//   bytes  0-3  : magic "HFTR"
//   bytes  4-7  : u32 LE  version (currently 1)
//   bytes  8-11 : u32 LE  num_buildings (= row count in the embeddings GeoJSON)
//   bytes 12-15 : u32 LE  feat_dim
//   bytes 16-..: f32 LE × num_buildings × feat_dim  (row-major, id-indexed)
//
// Each building's feature vector is stored at offset id*feat_dim. Non-finite
// floats (off-raster placeholder rows) are preserved verbatim and rejected
// downstream by isValidVector.
const SIDECAR_MAGIC = [0x48, 0x46, 0x54, 0x52]; // "HFTR"
const SIDECAR_VERSION = 1;

async function fetchFeaturesSidecar(url) {
  const t0 = performance.now();
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(
      `Failed to fetch features sidecar (HTTP ${resp.status}) at ${url}`
    );
  }
  const buf = await resp.arrayBuffer();
  if (buf.byteLength < 16) {
    throw new Error("Features sidecar is too short — header missing.");
  }
  const view = new DataView(buf);
  for (let i = 0; i < 4; i++) {
    if (view.getUint8(i) !== SIDECAR_MAGIC[i]) {
      throw new Error("Features sidecar has wrong magic — not an HFTR file.");
    }
  }
  const version = view.getUint32(4, /* littleEndian */ true);
  if (version !== SIDECAR_VERSION) {
    throw new Error(
      `Features sidecar version ${version} not supported (need ${SIDECAR_VERSION}).`
    );
  }
  const n = view.getUint32(8, true);
  const d = view.getUint32(12, true);
  const expected = 16 + n * d * 4;
  if (buf.byteLength !== expected) {
    throw new Error(
      `Features sidecar size mismatch: expected ${expected} bytes (16 + ${n} * ${d} * 4), got ${buf.byteLength}.`
    );
  }
  const matrix = new Float32Array(buf, 16, n * d);
  const ms = Math.round(performance.now() - t0);
  // eslint-disable-next-line no-console
  console.log(
    `[InteractiveLabeler] sidecar loaded: ${n} buildings × ${d} dims (${(buf.byteLength / (1024 * 1024)).toFixed(1)} MB) in ${ms} ms`
  );
  return { matrix, n, d };
}

const InteractiveLabeler = () => {
  const { projectId, imageLayerId, modelId } = useParams();
  const navigate = useNavigate();
  const { setIsLoading, setDialog, setAppHeaderRightButtons } =
    useContext(AppContext);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  // The Azure-Maps-wrapped Map's internal Mapbox-GL handle (for
  // setFeatureState / queryRenderedFeatures). null if findGlMap fails.
  const glMapRef = useRef(null);
  // Internal source/layer ids the renderer assigned to our PMTiles source
  // (Azure Maps may prefix/rename ours). Populated after map "ready".
  const internalSourceIdsRef = useRef([]);
  const internalLayerIdsRef = useRef([]);

  // labeledMap: id -> { label, features (Float32Array view), overtureId }.
  // predictionsMap: id -> class. Both survive tile load/unload — they live
  // in our React state, not on the rendered features. The map's feature-
  // state mirrors them so the renderer can color buildings without re-
  // reading our maps.
  const labeledMapRef = useRef({});
  const predictionsMapRef = useRef({});
  // Saved-labels keyed by Overture id, restored once from PutInteractiveLabels.
  // We can only re-apply them as feature-state once their tiles render
  // (the rendered feature carries both the row-index id and overture_id),
  // so we cache the map and consult it on every moveend re-hydration.
  const savedLabelsRef = useRef({});
  // Features sidecar: a single Float32Array of all per-building feature
  // vectors, packed row-major (id × dim). Populated once on createMap from
  // the HFTR binary sidecar (model.featuresSidecarUrl), then accessed via
  // lookupFeatureVector(id) on every label / viewport-predict path. No
  // more reading f_* from tile properties — PMTiles only carries id +
  // overture_id now.
  const sidecarRef = useRef(null); // { matrix: Float32Array, n, d }

  const boxRef = useRef(null); // box-select rectangle div
  const boxCleanupRef = useRef(null); // detaches document-level drag listeners
  const trainBusyRef = useRef(false);
  const trainPendingRef = useRef(false);
  // Cached trained model + invalidation flag. We only retrain when the
  // label set changes (recordLabel / clearLabel set labelsDirtyRef = true);
  // moveend re-predict reuses the cached model. This keeps panning the map
  // free of the "Training…" status that used to fire on every settle.
  const trainedModelRef = useRef(null);
  const labelsDirtyRef = useRef(true);
  const fullPredictAbortRef = useRef({ cancelled: false });

  const [isMapReady, setIsMapReady] = useState(false);
  const [selectedClass, setSelectedClass] = useState(CLASS_DAMAGED);
  const [viewMode, setViewMode] = useState("label"); // "label" | "predict"
  const [showFootprints, setShowFootprints] = useState(true);
  const [counts, setCounts] = useState({ 0: 0, 1: 0, 2: 0 });
  const [viewportPredicted, setViewportPredicted] = useState(0);
  const [metrics, setMetrics] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [status, setStatus] = useState("");
  const [mapInfo, setMapInfo] = useState({ lat: 0, lon: 0, zoom: 0 });
  // Progress state for the "Predict all buildings" full-coverage pass.
  const [fullPredict, setFullPredict] = useState(null);
  const [backend, setBackend] = useState(null);

  // selectedClass / viewMode are read by long-lived map event handlers.
  const selectedClassRef = useRef(selectedClass);
  useEffect(() => {
    selectedClassRef.current = selectedClass;
  }, [selectedClass]);
  const viewModeRef = useRef(viewMode);
  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);

  // Detect the compute backend up-front so the panel shows WebGPU vs CPU.
  useEffect(() => {
    let alive = true;
    getGpu().then((gpu) => {
      if (alive) setBackend(gpu ? "WebGPU" : "CPU");
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const init = async () => {
      if (!window.atlas) return;
      setIsLoading(true, "Loading Interactive Labeler");
      try {
        await createMap();
        setIsMapReady(true);
      } catch (e) {
        console.error("Error initializing interactive labeler:", e);
        setDialog(
          "Error",
          `Failed to load the interactive labeler: ${e?.message || e}`
        );
      } finally {
        setIsLoading(false);
      }
    };
    init();
    return () => {
      setAppHeaderRightButtons([]);
      if (boxCleanupRef.current) boxCleanupRef.current();
      if (mapRef.current) {
        mapRef.current.dispose();
        mapRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createMap() {
    let layerData = null;
    try {
      layerData = await apiGet(
        `GetLayerLabelingToolData?projectId=${projectId}&imageLayerId=${imageLayerId}`
      );
    } catch {
      // Imagery is optional — labeling works without it.
    }

    // Resolve the model's PMTiles URL. Models are returned by
    // GetLayerModelsDetails; pick ours by modelId. The pmtilesUrl is
    // populated by the embedding workflow's postprocessor.
    let pmtilesUrl = "";
    let sidecarUrl = "";
    try {
      const models = await apiGet(
        `GetLayerModelsDetails?projectId=${projectId}&imageLayerId=${imageLayerId}`
      );
      const model = (models || []).find(
        (m) => String(m.modelId) === String(modelId)
      );
      pmtilesUrl = model?.pmtilesUrl || "";
      sidecarUrl = model?.featuresSidecarUrl || "";
    } catch (e) {
      console.warn("Could not fetch model URLs:", e);
    }
    if (!pmtilesUrl) {
      throw new Error(
        "No PMTiles available for this model — the embedding workflow has not produced building tiles."
      );
    }
    if (!sidecarUrl) {
      throw new Error(
        "No features sidecar available for this model — re-embed the layer to produce one."
      );
    }
    // Fetch both artifacts through the same-origin API proxy: the
    // GetModelArtifact route streams the blob server-side via managed
    // identity. This keeps the browser off the firewalled storage account —
    // a direct *.blob SAS URL only works from allowlisted IPs, so
    // remote/mobile labelers hit a 403.
    const browserPmtilesUrl = buildUrl(
      `GetModelArtifact?projectId=${projectId}&modelId=${modelId}` +
        `&kind=pmtiles`
    );
    const browserSidecarUrl = buildUrl(
      `GetModelArtifact?projectId=${projectId}&modelId=${modelId}` +
        `&kind=sidecar`
    );

    // Download the whole archive once and serve pmtiles.js from memory. The
    // SWA /api proxy in front of the function app does not support HTTP range
    // requests (a ranged GET returns a full 200), so a network-backed
    // FetchSource fails with a byte-serving error. Reading the archive fully
    // and handing pmtiles an in-memory source makes every subsequent range
    // read hit the local buffer instead of the network. `getKey()` returns
    // browserPmtilesUrl so it matches the `pmtiles://<url>` source below.
    let pmtilesHeader = null;
    try {
      const pmtilesBuffer = await fetchArtifactBuffer(browserPmtilesUrl);
      const pm = new PMTiles(
        new InMemoryPMTilesSource(browserPmtilesUrl, pmtilesBuffer)
      );
      // Pre-register so the protocol can serve tile reads from the same handle.
      _pmtilesProtocol.add(pm);
      // Read the header so we can place the camera over the archive's bounds
      // (otherwise the map sits at [0, 0] zoom 3 and the user sees no tiles).
      pmtilesHeader = await pm.getHeader();
    } catch (e) {
      console.warn("Failed to load PMTiles archive (continuing):", e);
    }

    // Fetch the binary features sidecar and parse the HFTR header. The
    // resulting Float32Array view is the single source of truth for every
    // f_* lookup downstream — the PMTiles archive itself only carries id +
    // overture_id, so the labeler reads feature vectors here, not from
    // tile properties.
    setIsLoading(true, "Loading features…");
    sidecarRef.current = await fetchFeaturesSidecar(browserSidecarUrl);
    setIsLoading(true, "Loading Interactive Labeler");

    // Restore this model's previously-saved interactive labels (separate from
    // the Building Validation store). Labels are keyed by overture id; we
    // re-apply them as feature-state on each moveend hydration when the
    // matching building's tile is in view.
    try {
      const saved = await apiGet(
        `GetInteractiveLabels?projectId=${projectId}&modelId=${modelId}`
      );
      savedLabelsRef.current = saved?.labels || {};
    } catch {
      // No saved labels yet — start fresh.
    }

    // Resolve an initial camera position from the PMTiles header. The Map
    // constructor accepts {center, zoom} reliably (the {bounds} variant is
    // honored by setCamera but is silently ignored at construction time on
    // some Atlas builds — leaving the map at its default and the user
    // staring at empty water). centerLon/centerLat come from the PMTiles
    // header; centerZoom is the tippecanoe-suggested default (z<=maxZoom).
    let initialCamera = { center: [0, 0], zoom: 3 };
    if (pmtilesHeader) {
      const haveCenter =
        pmtilesHeader.centerLon != null && pmtilesHeader.centerLat != null;
      const centerLon = haveCenter
        ? pmtilesHeader.centerLon
        : (pmtilesHeader.minLon + pmtilesHeader.maxLon) / 2;
      const centerLat = haveCenter
        ? pmtilesHeader.centerLat
        : (pmtilesHeader.minLat + pmtilesHeader.maxLat) / 2;
      const zoom =
        pmtilesHeader.centerZoom ||
        Math.max(10, (pmtilesHeader.maxZoom || 14) - 1);
      initialCamera = { center: [centerLon, centerLat], zoom };
    }

    const map = new window.atlas.Map(mapContainerRef.current, {
      ...initialCamera,
      maxPitch: 0,
      pitch: 0,
      style: isAzureMapsPlaceholder ? "blank" : "satellite",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
    });

    map.events.add("ready", () => {
      map.setUserInteraction({
        dragRotateInteraction: false,
        scrollZoomInteraction: true,
        pinchZoomInteraction: true,
        pinchRotateInteraction: false,
      });
      map.controls.add(new window.atlas.control.ZoomControl(), {
        position: "bottom-left",
      });

      if (layerData?.imagery?.preEventTileUrl) {
        loadImagery(
          toBrowserTitilerUrl(layerData.imagery.preEventTileUrl),
          map,
          { current: null },
          "preEventImageryLayer",
          false
        );
      }
      if (layerData?.imagery?.postEventTileUrl) {
        loadImagery(
          toBrowserTitilerUrl(layerData.imagery.postEventTileUrl),
          map,
          { current: null },
          "postEventImageryLayer",
          true
        );
      }

      // Footprints come from the PMTiles archive (tippecanoe -l buildings,
      // with --use-attribute-for-id=id so each MVT feature carries the
      // native integer feature id needed by setFeatureState).
      // Footprints come from the PMTiles archive (tippecanoe -l buildings,
      // with --use-attribute-for-id=id so each MVT feature carries the
      // native integer feature id needed by setFeatureState).
      //
      // Deliberately do NOT pass minSourceZoom/maxSourceZoom here: the
      // pmtiles.js protocol handler advertises the archive's actual zoom
      // range to the renderer via its TileJSON response, and the renderer
      // then overzooms tiles at z>maxZoom automatically. Setting
      // maxSourceZoom explicitly capped at 14 makes Atlas treat z>14 as
      // "source has no data" and stop rendering past that zoom.
      const source = new window.atlas.source.VectorTileSource("buildings", {
        type: "vector",
        url: `pmtiles://${browserPmtilesUrl}`,
        // Per AZURE_MAPS_INTERACTIVE_LABELER.md §3 Azure Maps silently
        // ignores promoteId — but our tiles already have feature ids baked
        // in, so it's harmless to pass. Useful as a hint for any future
        // SDK update that honors it.
        promoteId: { [PMTILES_SOURCE_LAYER]: "id" },
      });
      map.sources.add(source);

      // Layer maxZoom > source maxzoom is how the renderer is told to
      // overzoom: vector tiles get scaled up for z>source.maxzoom up to
      // the layer's maxZoom. 24 is the Mapbox/Atlas hard ceiling.
      const fillLayer = new window.atlas.layer.PolygonLayer(
        "buildings",
        "embeddingFill",
        {
          sourceLayer: PMTILES_SOURCE_LAYER,
          fillColor: fillColorExpr("label"),
          fillOpacity: fillOpacityExpr("label"),
        }
      );
      map.layers.add(fillLayer);

      map.layers.add(
        new window.atlas.layer.LineLayer("buildings", "embeddingOutline", {
          sourceLayer: PMTILES_SOURCE_LAYER,
          strokeColor: "#1a5276",
          // Outlines are noise when zoomed out: hide them below z15, draw
          // them thin in the z15-16 transition, and use the full width once
          // the user is zoomed in past z16.
          minZoom: 15,
          strokeWidth: ["step", ["zoom"], 1, 16, 2],
        })
      );

      // §4: reach the internal Mapbox-GL map for setFeatureState +
      // queryRenderedFeatures. Without it, we can render but can't recolor
      // individual buildings on click.
      const glMap = findGlMap(map);
      glMapRef.current = glMap;
      if (!glMap) {
        setStatus(
          "Cannot reach the internal map renderer — labeling will not show colors."
        );
      } else if (typeof glMap.getStyle === "function") {
        // Discover the source/layer ids the renderer actually uses (Azure
        // Maps prefixes ours). queryRenderedFeatures must target the
        // internal ids, and setFeatureState must use the source id the
        // renderer assigned.
        try {
          const style = glMap.getStyle();
          const srcs = Object.keys(style.sources || {});
          const ours = srcs.filter(
            (s) => s === "buildings" || /build/i.test(s)
          );
          internalSourceIdsRef.current = [
            ...new Set(["buildings", ...ours, ...srcs]),
          ];
          internalLayerIdsRef.current = (style.layers || [])
            .filter(
              (l) =>
                l.type === "fill" &&
                (internalSourceIdsRef.current.includes(l.source) ||
                  /build/i.test(l.id))
            )
            .map((l) => l.id);
        } catch (e) {
          console.warn("glMap.getStyle() failed:", e);
        }
      }

      // Click → label the building under the cursor. Box-select (Ctrl+drag)
      // is wired below. Both call into labelBuilding(s) which updates
      // labeledMap + feature-state + (in predict view) re-runs the model.
      map.events.add("click", fillLayer, (e) => {
        if (
          e.originalEvent &&
          (e.originalEvent.ctrlKey || e.originalEvent.metaKey)
        ) {
          return;
        }
        const f = clickedFeature(map, e);
        if (!f) return;
        labelBuilding(f.id, f.properties, selectedClassRef.current);
      });
      map.events.add("contextmenu", fillLayer, (e) => {
        const f = clickedFeature(map, e);
        if (!f) return;
        clearLabel(f.id);
        return false;
      });
      map.getCanvasContainer().style.cursor = "pointer";
      setupBoxSelect(map);

      // Hydrate viewport features each time the map settles. This:
      //  (a) detects feature keys on the first f_* props we see;
      //  (b) restores any saved labels for buildings that just rendered;
      //  (c) runs viewport-scoped predict if the model has training data.
      const hydrate = () => hydrateViewport(map);
      map.events.add("moveend", hydrate);
      map.events.add("sourcedata", (e) => {
        // Only react when the buildings source finishes loading a tile.
        if (
          e &&
          e.isSourceLoaded &&
          internalSourceIdsRef.current.includes(e.sourceId)
        ) {
          hydrate();
        }
      });
      hydrate();

      // Info bar: keep lat/lon/zoom in sync as the camera moves.
      const syncInfo = () => {
        const cam = map.getCamera();
        const center = cam.center || [0, 0];
        setMapInfo({
          lon: center[0],
          lat: center[1],
          zoom: cam.zoom || 0,
        });
      };
      map.events.add("move", syncInfo);
      syncInfo();
    });

    mapRef.current = map;
  }

  // ── Internal-map helpers ──────────────────────────────────────────────────
  // Walk the rendered features at a click point and return the first one
  // from our buildings layer, with its id + props (which include f_*).
  function clickedFeature(map, e) {
    const gl = glMapRef.current;
    if (!gl) return null;
    let px = e.pixel;
    if (!px && e.position) {
      const pos = map.positionsToPixels([e.position]);
      px = pos && pos[0];
    }
    if (!px) return null;
    let rf = [];
    try {
      rf = gl.queryRenderedFeatures(
        px,
        internalLayerIdsRef.current.length
          ? { layers: internalLayerIdsRef.current }
          : undefined
      );
    } catch (err) {
      console.warn("queryRenderedFeatures failed:", err);
      return null;
    }
    const f = rf[0];
    if (!f || f.id == null) return null;
    return { id: f.id, properties: f.properties, source: f.source };
  }

  // Read all currently-rendered features from the buildings layer, hydrate
  // featureKeys / saved labels / viewport predictions. Idempotent.
  function hydrateViewport(map) {
    const gl = glMapRef.current;
    if (!gl) return;
    if (!internalLayerIdsRef.current.length) return;
    let features = [];
    try {
      features = gl.queryRenderedFeatures(undefined, {
        layers: internalLayerIdsRef.current,
      });
    } catch (err) {
      console.warn("queryRenderedFeatures (viewport) failed:", err);
      return;
    }
    if (features.length === 0) return;

    // Restore any saved labels whose tiles are now in view.
    const saved = savedLabelsRef.current;
    if (saved && Object.keys(saved).length > 0) {
      let restored = 0;
      for (const f of features) {
        const id = f.id;
        if (id == null || labeledMapRef.current[id]) continue;
        const overtureId = f.properties?.overture_id ?? id;
        const entry = saved[overtureId];
        if (!entry) continue;
        const cls = VALIDATION_TO_CLASS[entry.label];
        if (cls == null) continue;
        const vec = lookupFeatureVector(id);
        if (!vec) continue;
        labeledMapRef.current[id] = {
          label: cls,
          features: vec,
          overtureId,
        };
        setFeatureStateLabel(f.source, id, cls);
        restored++;
      }
      if (restored > 0) {
        labelsDirtyRef.current = true;
        refreshCounts();
      }
    }

    // Re-apply in-session labels / predictions for any buildings whose
    // tile just (re-)loaded — feature-state survives tile unload, but
    // freshly-tessellated features render with empty state.
    for (const f of features) {
      const id = f.id;
      if (id == null) continue;
      const entry = labeledMapRef.current[id];
      if (entry) setFeatureStateLabel(f.source, id, entry.label);
      const pred = predictionsMapRef.current[id];
      if (pred != null) setFeatureStatePred(f.source, id, pred);
    }

    // Viewport-scoped predict — only train + score what's on screen.
    if (viewModeRef.current === "predict") {
      maybeTrainAndPredict(features);
    }
  }

  // ── feature-state helpers (drive renderer paint) ──────────────────────────
  function setFeatureStateLabel(sourceId, id, cls) {
    const gl = glMapRef.current;
    if (!gl) return;
    try {
      gl.setFeatureState(
        { source: sourceId, sourceLayer: PMTILES_SOURCE_LAYER, id },
        { label: cls }
      );
      mapRef.current?.triggerRepaint && mapRef.current.triggerRepaint();
    } catch (err) {
      console.warn("setFeatureState (label) failed:", err);
    }
  }
  function setFeatureStatePred(sourceId, id, cls) {
    const gl = glMapRef.current;
    if (!gl) return;
    try {
      gl.setFeatureState(
        { source: sourceId, sourceLayer: PMTILES_SOURCE_LAYER, id },
        { pred: cls }
      );
      mapRef.current?.triggerRepaint && mapRef.current.triggerRepaint();
    } catch (err) {
      console.warn("setFeatureState (pred) failed:", err);
    }
  }
  function clearFeatureStateLabel(sourceId, id) {
    const gl = glMapRef.current;
    if (!gl) return;
    try {
      gl.removeFeatureState(
        { source: sourceId, sourceLayer: PMTILES_SOURCE_LAYER, id },
        "label"
      );
      mapRef.current?.triggerRepaint && mapRef.current.triggerRepaint();
    } catch (err) {
      console.warn("removeFeatureState failed:", err);
    }
  }
  // The renderer may have given our source an internal name; pick the first
  // id from the discovered list (the click handler uses the feature's own
  // .source so this only matters for state writes not driven by a click).
  function primarySourceId() {
    return internalSourceIdsRef.current[0] || "buildings";
  }

  // ── Repaint when the view-mode toggle flips ───────────────────────────────
  // We don't recreate the layer — we mutate its fillColor/fillOpacity
  // expressions so the renderer reads the right feature-state key without
  // re-tessellating.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const fill = map.layers.getLayerById?.("embeddingFill");
    if (!fill) return;
    fill.setOptions({
      fillColor: fillColorExpr(viewMode === "predict" ? "pred" : "label"),
      fillOpacity: fillOpacityExpr(viewMode === "predict" ? "pred" : "label"),
    });
    if (viewMode === "predict") hydrateViewport(map);
  }, [viewMode, isMapReady]);

  // Show / hide the buildings layers without unmounting them. Driven by
  // the panel toggle + spacebar hotkey; the feature-state and the cached
  // labels both survive a hide/show cycle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const layerId of ["embeddingFill", "embeddingOutline"]) {
      const layer = map.layers.getLayerById?.(layerId);
      if (layer) layer.setOptions({ visible: showFootprints });
    }
  }, [showFootprints, isMapReady]);

  // ── Sidecar feature lookup ────────────────────────────────────────────────
  // Returns a Float32Array view (no copy) into the sidecar matrix at the
  // row for this building id, or null if the id is out of range / sidecar
  // not yet loaded. The view is a zero-copy slice of the underlying buffer;
  // callers should NOT mutate it.
  function lookupFeatureVector(id) {
    const sc = sidecarRef.current;
    if (!sc) return null;
    if (typeof id !== "number" || id < 0 || id >= sc.n) return null;
    return sc.matrix.subarray(id * sc.d, (id + 1) * sc.d);
  }

  // ── Labeling ──────────────────────────────────────────────────────────────
  function recordLabel(id, props, cls) {
    const vec = lookupFeatureVector(id);
    if (!vec) return false;
    // Capture the Overture id (when present) up front so the save path
    // doesn't have to guess. The persisted store is keyed by Overture id
    // (so labels survive a re-embed that renumbers row-index ids); the
    // hydrate path also looks up by Overture id on restore.
    const overtureId =
      props && props.overture_id != null ? props.overture_id : id;
    labeledMapRef.current[id] = {
      label: cls,
      features: vec,
      overtureId,
    };
    // Any label change invalidates the cached trained model; the next
    // viewport predict will retrain. Clearing also invalidates.
    labelsDirtyRef.current = true;
    return true;
  }
  function labelBuilding(id, props, cls) {
    if (!recordLabel(id, props, cls)) return;
    setFeatureStateLabel(primarySourceId(), id, cls);
    refreshCounts();
    if (viewModeRef.current === "predict") {
      hydrateViewport(mapRef.current);
    }
  }
  function labelBuildings(items, cls) {
    let n = 0;
    for (const it of items) {
      if (it && it.id != null && recordLabel(it.id, it.properties, cls)) {
        setFeatureStateLabel(it.source || primarySourceId(), it.id, cls);
        n++;
      }
    }
    if (n === 0) return;
    refreshCounts();
    setStatus(`Labeled ${n} buildings.`);
    if (viewModeRef.current === "predict") {
      hydrateViewport(mapRef.current);
    }
  }
  function clearLabel(id) {
    delete labeledMapRef.current[id];
    labelsDirtyRef.current = true;
    clearFeatureStateLabel(primarySourceId(), id);
    refreshCounts();
  }
  function refreshCounts() {
    const next = { 0: 0, 1: 0, 2: 0 };
    Object.values(labeledMapRef.current).forEach((e) => {
      next[e.label] = (next[e.label] || 0) + 1;
    });
    setCounts(next);
  }

  // ── Ctrl+drag box-select (viewport-scoped) ────────────────────────────────
  function setupBoxSelect(map) {
    const canvas = map.getCanvasContainer();
    let origin = null;

    const onDown = (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      e.stopPropagation();
      map.setUserInteraction({ dragPanInteraction: false });
      const rect = canvas.getBoundingClientRect();
      origin = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      const box = boxRef.current;
      if (box) {
        box.style.display = "block";
        box.style.left = origin.x + "px";
        box.style.top = origin.y + "px";
        box.style.width = "0px";
        box.style.height = "0px";
      }
    };

    const onMove = (e) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const box = boxRef.current;
      if (box) {
        box.style.left = Math.min(origin.x, x) + "px";
        box.style.top = Math.min(origin.y, y) + "px";
        box.style.width = Math.abs(x - origin.x) + "px";
        box.style.height = Math.abs(y - origin.y) + "px";
      }
    };

    const onUp = (e) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const x1 = Math.min(origin.x, e.clientX - rect.left);
      const y1 = Math.min(origin.y, e.clientY - rect.top);
      const x2 = Math.max(origin.x, e.clientX - rect.left);
      const y2 = Math.max(origin.y, e.clientY - rect.top);
      origin = null;
      if (boxRef.current) boxRef.current.style.display = "none";
      map.setUserInteraction({ dragPanInteraction: true });
      if (x2 - x1 < 4 || y2 - y1 < 4) return;

      const gl = glMapRef.current;
      if (!gl) return;
      let rf = [];
      try {
        rf = gl.queryRenderedFeatures(
          [
            [x1, y1],
            [x2, y2],
          ],
          internalLayerIdsRef.current.length
            ? { layers: internalLayerIdsRef.current }
            : undefined
        );
      } catch (err) {
        console.warn("box-select queryRenderedFeatures failed:", err);
        return;
      }
      const items = rf
        .filter((f) => f.id != null)
        .map((f) => ({ id: f.id, properties: f.properties, source: f.source }));
      labelBuildings(items, selectedClassRef.current);
    };

    canvas.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    boxCleanupRef.current = () => {
      canvas.removeEventListener("mousedown", onDown);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }

  // ── Viewport-scoped train + predict ───────────────────────────────────────
  // Train ONCE per label-set change (labelsDirtyRef flips on every label/
  // clear/restore), then reuse the cached model on every viewport settle.
  // Without this, panning a settled labeler triggered a full retrain on
  // each moveend — visible to the user as a flickering "Training…" status.
  async function maybeTrainAndPredict(viewportFeatures) {
    if (trainBusyRef.current) {
      trainPendingRef.current = true;
      return;
    }
    const entries = Object.values(labeledMapRef.current).filter((e) =>
      isValidVector(e.features)
    );
    const perClass = {};
    entries.forEach((e) => (perClass[e.label] = (perClass[e.label] || 0) + 1));
    const classesReady = Object.values(perClass).filter(
      (n) => n >= MIN_PER_CLASS
    ).length;
    if (classesReady < 2) {
      setStatus(
        `Need ${MIN_PER_CLASS}+ labels in at least 2 classes to train.`
      );
      return;
    }

    trainBusyRef.current = true;
    try {
      // Only retrain when the label set actually changed. The metrics panel
      // is paired with training, so it refreshes on the same cadence.
      if (labelsDirtyRef.current || !trainedModelRef.current) {
        setStatus("Training…");
        const metrics = await holdoutMetricsDamaged(
          entries,
          0.2,
          CLASS_DAMAGED
        );
        if (metrics) setMetrics({ ...metrics, mode: "holdout" });
        const ovr = new OvRLogisticRegression({
          learningRate: 0.1,
          numSteps: 500,
          lambda: 0.01,
        });
        ovr.train(
          entries.map((e) => e.features),
          entries.map((e) => e.label)
        );
        trainedModelRef.current = ovr;
        labelsDirtyRef.current = false;
        // The backend label is purely cosmetic for the cached path —
        // training is CPU-only here, but the WebGPU label still applies
        // to the holdout-metrics path if a GPU was detected.
        setBackend((b) => b || "CPU");
      }

      // Score only the buildings currently in the viewport. Feature
      // vectors come from the in-memory sidecar (no f_* in the tiles).
      const ids = [];
      const matrix = [];
      const sources = [];
      for (const f of viewportFeatures) {
        if (f.id == null) continue;
        const vec = lookupFeatureVector(f.id);
        if (!isValidVector(vec)) continue;
        ids.push(f.id);
        matrix.push(vec);
        sources.push(f.source);
      }
      if (matrix.length === 0) return;

      const predictions = trainedModelRef.current.predict(matrix);
      for (let i = 0; i < ids.length; i++) {
        predictionsMapRef.current[ids[i]] = predictions[i];
        setFeatureStatePred(sources[i], ids[i], predictions[i]);
      }
      setViewportPredicted(ids.length);
      setStatus(
        `Predicted ${ids.length} buildings in viewport (${entries.length} labels).`
      );
    } finally {
      trainBusyRef.current = false;
      if (trainPendingRef.current) {
        trainPendingRef.current = false;
        hydrateViewport(mapRef.current);
      }
    }
  }

  // ── Keyboard: 1/2/3 set class, T cycles, P toggles view, Space hides ─────
  useEffect(() => {
    function onKeyDown(e) {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
      if (e.key === "1") setSelectedClass(CLASS_INTACT);
      else if (e.key === "2") setSelectedClass(CLASS_DAMAGED);
      else if (e.key === "3") setSelectedClass(CLASS_CLOUDY);
      else if (e.key === "t" || e.key === "T")
        setSelectedClass((c) => (c + 1) % 3);
      else if (e.key === "p" || e.key === "P")
        setViewMode((v) => (v === "label" ? "predict" : "label"));
      else if (e.key === " " || e.code === "Space") {
        // preventDefault to stop the browser from scrolling the page
        // when the map container doesn't have focus.
        e.preventDefault();
        setShowFootprints((v) => !v);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // ── Save labels ───────────────────────────────────────────────────────────
  // Persists the manual labels to the model-scoped interactive-labeler store.
  // Predictions are persisted by the separate "Predict all buildings" flow
  // below — labels and predictions are saved independently so users can
  // checkpoint labels without paying for a full-coverage predict pass.
  async function handleSaveLabels() {
    setIsSaving(true);
    setIsLoading(true, "Saving labels…");
    try {
      const labels = {};
      for (const [id, entry] of Object.entries(labeledMapRef.current)) {
        const overtureId = entry.overtureId ?? id;
        labels[overtureId] = {
          id: overtureId,
          label: CLASS_TO_VALIDATION[entry.label],
          updatedAt: new Date().toISOString(),
        };
      }
      await apiPut("PutInteractiveLabels", {
        projectId,
        imageLayerId,
        modelId,
        labels,
      });
      setDialog("Saved", "Labels saved successfully.", [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => setDialog(),
        },
      ]);
    } catch (e) {
      console.error("Error saving labels:", e);
      setDialog("Error", "Failed to save labels.");
    } finally {
      setIsSaving(false);
      setIsLoading(false);
    }
  }

  // ── Clear all labels (in-memory + persisted) ──────────────────────────────
  // Wipes the in-session labeledMap, drops the cached model (so the next
  // predict pass falls back to "need more labels"), removes the label
  // feature-state for every rendered building, AND overwrites the
  // persisted store with an empty document so revisiting the labeler
  // doesn't restore the cleared labels.
  function handleClearLabels() {
    const total =
      counts[CLASS_INTACT] + counts[CLASS_DAMAGED] + counts[CLASS_CLOUDY];
    const message =
      total > 0
        ? `Clear all ${total} label(s) and predictions for this model? This removes them from the database and cannot be undone.`
        : "Clear any saved labels and predictions for this model? This cannot be undone.";
    setDialog("Are you sure?", message, [
      {
        type: "primary",
        key: "yes",
        text: "Clear labels",
        onClick: async () => {
          setDialog();
          setIsLoading(true, "Clearing labels…");
          try {
            // Clear ALL feature-state for the buildings source in one
            // call per source (instead of per-feature, which freezes the
            // browser on large viewports).
            const gl = glMapRef.current;
            if (gl) {
              for (const sourceId of internalSourceIdsRef.current) {
                try {
                  gl.removeFeatureState(
                    { source: sourceId, sourceLayer: PMTILES_SOURCE_LAYER }
                  );
                } catch { /* ignore */ }
              }
              mapRef.current?.triggerRepaint && mapRef.current.triggerRepaint();
            }
            // In-memory reset (labels + predictions).
            labeledMapRef.current = {};
            savedLabelsRef.current = {};
            predictionsMapRef.current = {};
            trainedModelRef.current = null;
            labelsDirtyRef.current = true;
            refreshCounts();
            setMetrics(null);
            setViewportPredicted(0);
            setStatus("Cleared all labels and predictions.");
            // Persist empty labels and empty predictions so the DB
            // matches the UI state.
            await apiPut("PutInteractiveLabels", {
              projectId,
              imageLayerId,
              modelId,
              labels: {},
            });
            await apiPut("PutBuildingPredictions", {
              projectId,
              imageLayerId,
              modelId,
              predictions: [],
            });
          } catch (e) {
            console.error("Error clearing labels:", e);
            setDialog("Error", "Failed to clear labels from the server.");
            return;
          } finally {
            setIsLoading(false);
          }
        },
      },
      {
        type: "default",
        key: "no",
        text: "Cancel",
        onClick: () => setDialog(),
      },
    ]);
  }

  // ── Full-coverage Predict-all-buildings flow ──────────────────────────────
  // Downloads the full embeddings GeoJSON once, trains the OvR model on every
  // available label, batches predict over every building with a progress
  // modal, then PUTs predictions so the Validation/Assessment reports have
  // full coverage. Cancellable via fullPredictAbortRef.
  async function handlePredictAll() {
    const entries = Object.values(labeledMapRef.current).filter((e) =>
      isValidVector(e.features)
    );
    const perClass = {};
    entries.forEach((e) => (perClass[e.label] = (perClass[e.label] || 0) + 1));
    const classesReady = Object.values(perClass).filter(
      (n) => n >= MIN_PER_CLASS
    ).length;
    if (classesReady < 2) {
      setDialog(
        "Not enough labels",
        `You need at least ${MIN_PER_CLASS} labels in 2+ classes before predicting on all buildings.`
      );
      return;
    }

    fullPredictAbortRef.current = { cancelled: false };
    setFullPredict({ phase: "train", message: "Training model…" });

    try {
      // 1. The sidecar is already loaded — no network hit. Build (id, vector)
      // arrays straight from the in-memory Float32Array, dropping buildings
      // with non-finite vectors (off-raster placeholders).
      const sc = sidecarRef.current;
      if (!sc) throw new Error("Features sidecar not loaded yet.");
      const ids = [];
      const matrix = [];
      for (let i = 0; i < sc.n; i++) {
        const vec = sc.matrix.subarray(i * sc.d, (i + 1) * sc.d);
        if (!isValidVector(vec)) continue;
        ids.push(i);
        matrix.push(vec);
      }
      if (matrix.length === 0) {
        throw new Error(
          "No buildings with valid feature vectors in the loaded sidecar."
        );
      }

      // 2. Train the OvR model once on every label (CPU path — cheap to
      // train, predict-only is cheap per batch, and batch sizes are huge).
      const ovr = new OvRLogisticRegression({
        learningRate: 0.1,
        numSteps: 500,
        lambda: 0.01,
      });
      ovr.train(
        entries.map((e) => e.features),
        entries.map((e) => e.label)
      );
      if (fullPredictAbortRef.current.cancelled) {
        setFullPredict(null);
        return;
      }

      // 4. Batched predict over every building, with a progress callback
      // per batch so the modal feels responsive on large layers.
      const total = matrix.length;
      const predictions = new Array(total);
      let done = 0;
      for (let start = 0; start < total; start += FULL_PREDICT_BATCH) {
        if (fullPredictAbortRef.current.cancelled) {
          setFullPredict(null);
          return;
        }
        const end = Math.min(total, start + FULL_PREDICT_BATCH);
        const batch = matrix.slice(start, end);
        const preds = ovr.predict(batch);
        for (let i = 0; i < preds.length; i++) {
          predictions[start + i] = preds[i];
        }
        done = end;
        setFullPredict({
          phase: "predict",
          current: done,
          total,
          message: `Predicting ${done.toLocaleString()} / ${total.toLocaleString()}…`,
        });
        // Yield to the browser so the progress bar repaints.
        await new Promise((r) => setTimeout(r, 0));
      }

      // 5. Persist. predictionsMap also gets refreshed so the in-session
      // predict view immediately shows the full-coverage result.
      setFullPredict({ phase: "save", message: "Saving predictions…" });
      const predMap = {};
      const payload = [];
      for (let i = 0; i < ids.length; i++) {
        const cls = predictions[i];
        predMap[ids[i]] = cls;
        payload.push({
          id: ids[i],
          damaged: cls === CLASS_DAMAGED ? 1 : 0,
          unknown: cls === CLASS_CLOUDY ? 1.0 : 0.0,
        });
      }
      predictionsMapRef.current = {
        ...predictionsMapRef.current,
        ...predMap,
      };
      await apiPut("PutBuildingPredictions", {
        projectId,
        imageLayerId,
        modelId,
        predictions: payload,
      });
      // Re-apply to the rendered viewport.
      if (mapRef.current) hydrateViewport(mapRef.current);

      setFullPredict(null);
      setDialog(
        "Done",
        `Predicted ${total.toLocaleString()} buildings and saved.`,
        [
          {
            type: "primary",
            key: "close",
            text: "Close",
            onClick: () => setDialog(),
          },
        ]
      );
    } catch (e) {
      console.error("Predict-all failed:", e);
      setFullPredict(null);
      setDialog("Error", `Predict-all failed: ${e?.message || e}`);
    }
  }

  function cancelPredictAll() {
    fullPredictAbortRef.current.cancelled = true;
  }

  const totalLabeled = counts[0] + counts[1] + counts[2];

  return (
    <div
      style={{
        display: "flex",
        flexGrow: 1,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 10,
          left: 10,
          zIndex: 1000,
          backgroundColor: "rgba(255, 255, 255, 1)",
          padding: "5px 10px",
          borderRadius: "5px",
        }}
      >
        <ActionButton
          id="backButton"
          iconProps={{ iconName: "ChevronLeft" }}
          onClick={() => navigate(`/project/${projectId}`)}
        >
          Back
        </ActionButton>
      </div>

      <div
        ref={mapContainerRef}
        id="interactiveLabelerMap"
        style={{ flexGrow: 1 }}
      />

      {isMapReady && (
        <div
          style={{
            width: 280,
            padding: 16,
            background: "#fff",
            borderLeft: "1px solid #e1e1e1",
            overflowY: "auto",
          }}
        >
          <Text variant="large" block style={{ marginBottom: 2 }}>
            Interactive Labeler
          </Text>
          {backend && (
            <div
              style={{
                fontSize: 11,
                color: backend === "WebGPU" ? "#0a7d33" : "#888",
                marginBottom: 8,
              }}
            >
              Compute: {backend}
            </div>
          )}

          <ChoiceGroup
            label="Set class"
            selectedKey={String(selectedClass)}
            options={CLASS_OPTIONS}
            onChange={(e, o) => setSelectedClass(parseInt(o.key, 10))}
          />

          <div style={{ marginTop: 8, fontSize: 13 }}>
            <div style={{ color: CLASS_COLORS[CLASS_INTACT] }}>
              Intact: <b>{counts[CLASS_INTACT]}</b>
            </div>
            <div style={{ color: CLASS_COLORS[CLASS_DAMAGED] }}>
              Damaged: <b>{counts[CLASS_DAMAGED]}</b>
            </div>
            <div style={{ color: CLASS_COLORS[CLASS_CLOUDY] }}>
              Cloudy: <b>{counts[CLASS_CLOUDY]}</b>
            </div>
          </div>

          <Toggle
            label="View"
            onText="Predicted"
            offText="Labeled"
            checked={viewMode === "predict"}
            onChange={(e, checked) =>
              setViewMode(checked ? "predict" : "label")
            }
            style={{ marginTop: 12 }}
          />

          <Toggle
            label="Footprints"
            onText="Visible"
            offText="Hidden"
            checked={showFootprints}
            onChange={(e, checked) => setShowFootprints(!!checked)}
          />

          {metrics && (
            <div
              style={{
                marginTop: 10,
                fontSize: 12,
                color: "#333",
                borderTop: "1px solid #eee",
                paddingTop: 8,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                Damaged class (80/20 holdout)
              </div>
              <div style={{ display: "flex", gap: 12 }}>
                <span>
                  P <b>{(metrics.precision * 100).toFixed(0)}%</b>
                </span>
                <span>
                  R <b>{(metrics.recall * 100).toFixed(0)}%</b>
                </span>
                <span>
                  F1 <b>{(metrics.f1 * 100).toFixed(0)}%</b>
                </span>
              </div>
              <div style={{ color: "#999", marginTop: 2 }}>
                {metrics.nPos} damaged / {metrics.nNeg} other
              </div>
            </div>
          )}

          <div
            style={{
              marginTop: 8,
              minHeight: 18,
              fontSize: 12,
              color: "#888",
            }}
          >
            {status}
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "#888" }}>
            {totalLabeled} labeled · {viewportPredicted} predicted in viewport
          </div>

          <PrimaryButton
            text={isSaving ? "Saving…" : "Save labels"}
            disabled={isSaving || totalLabeled === 0}
            onClick={handleSaveLabels}
            style={{ marginTop: 16, width: "100%" }}
          />
          <DefaultButton
            text="Predict all buildings"
            disabled={!!fullPredict || totalLabeled === 0}
            onClick={handlePredictAll}
            style={{ marginTop: 8, width: "100%" }}
            title="Run the trained model across every building in the layer (not just the viewport) and persist the predictions for the Validation / Assessment reports."
          />
          <DefaultButton
            text="Clear labels"
            onClick={handleClearLabels}
            style={{ marginTop: 8, width: "100%", color: "#a4262c" }}
            title="Remove every label for this model — both in-session and in the saved store."
          />

          <div style={{ marginTop: 12, fontSize: 11, color: "#999" }}>
            Click a building to label it · right-click to clear ·{" "}
            <kbd>Ctrl</kbd>+drag to box-label · <kbd>1</kbd>/<kbd>2</kbd>/
            <kbd>3</kbd> set class · <kbd>P</kbd> toggle view ·{" "}
            <kbd>Space</kbd> show/hide footprints
          </div>
        </div>
      )}

      {/* Box-select rectangle (Ctrl+drag) */}
      <div
        ref={boxRef}
        style={{
          position: "absolute",
          display: "none",
          border: "2px dashed #3388ff",
          background: "rgba(51,136,255,0.15)",
          pointerEvents: "none",
          zIndex: 900,
        }}
      />

      {/* Full-coverage Predict-all progress modal. */}
      {fullPredict && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(0,0,0,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 2000,
          }}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 8,
              padding: 24,
              minWidth: 380,
              maxWidth: 480,
              boxShadow: "0 4px 18px rgba(0,0,0,0.3)",
            }}
          >
            <Text variant="large" block style={{ marginBottom: 8 }}>
              Predict all buildings
            </Text>
            <div style={{ fontSize: 13, color: "#444", marginBottom: 12 }}>
              {fullPredict.message}
            </div>
            <ProgressIndicator
              percentComplete={
                fullPredict.phase === "predict" && fullPredict.total
                  ? fullPredict.current / fullPredict.total
                  : undefined
              }
            />
            <div
              style={{ marginTop: 14, display: "flex", justifyContent: "flex-end" }}
            >
              <DefaultButton
                text="Cancel"
                onClick={cancelPredictAll}
                disabled={fullPredict.phase === "save"}
              />
            </div>
          </div>
        </div>
      )}

      {/* Bottom info bar: lat / lon / zoom */}
      {isMapReady && (
        <div
          style={{
            position: "absolute",
            bottom: 6,
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(255,255,255,0.95)",
            padding: "4px 12px",
            borderRadius: 6,
            boxShadow: "0 1px 4px rgba(0,0,0,0.15)",
            zIndex: 900,
            fontSize: 12,
            fontFamily: "monospace",
            color: "#444",
            whiteSpace: "nowrap",
          }}
        >
          Zoom: {mapInfo.zoom.toFixed(2)} | Lat: {mapInfo.lat.toFixed(4)}, Lon:{" "}
          {mapInfo.lon.toFixed(4)}
        </div>
      )}
    </div>
  );
};

export default InteractiveLabeler;
