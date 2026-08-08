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
  Button,
  Divider,
  Field,
  ProgressBar,
  Radio,
  RadioGroup,
  Spinner,
  Switch,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
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
  crossValidateMetrics,
  holdoutMetricsDamaged,
  isValidVector,
} from "./interactiveModel.js";
import { getGpu } from "./gpuLogreg.js";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp.jsx";
import {
  INTERACTIVE_LABELER_SHORTCUTS,
  shouldIgnoreShortcut,
} from "../keyboardShortcuts.js";

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
// Human-readable class names, indexed by class number (parallel to CLASS_COLORS).
const CLASS_LABELS = ["Intact", "Damaged", "Cloudy"];
const UNLABELED_COLOR = "#BDBDBD";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexGrow: 1,
    minHeight: 0,
    height: "calc(100dvh - 40px - var(--footer-height, 0px))",
    position: "relative",
    isolation: "isolate",
    overflow: "hidden",
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  mapBadge: {
    position: "absolute",
    top: "10px",
    zIndex: 1000,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    whiteSpace: "nowrap",
    pointerEvents: "none",
  },
  mapBadgeRight: {
    right: "calc(clamp(280px, 24vw, 340px) + 20px)",
    "@media (max-width: 700px)": {
      right: "10px",
    },
  },
  legend: {
    position: "absolute",
    right: "calc(clamp(280px, 24vw, 340px) + 20px)",
    bottom: "10px",
    zIndex: 900,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow8,
    fontSize: tokens.fontSizeBase100,
    lineHeight: tokens.lineHeightBase200,
    pointerEvents: "none",
    "@media (max-width: 700px)": {
      right: "8px",
      bottom: "calc(55% + 18px)",
    },
  },
  secondaryText: {
    color: tokens.colorNeutralForeground3,
  },
  sidePanel: {
    position: "absolute",
    top: "10px",
    right: "10px",
    bottom: "10px",
    zIndex: 1000,
    boxSizing: "border-box",
    width: "clamp(280px, 24vw, 340px)",
    maxWidth: "calc(100% - 20px)",
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow16,
    display: "flex",
    flexDirection: "column",
    color: tokens.colorNeutralForeground1,
    "@media (max-width: 700px)": {
      top: "auto",
      right: "8px",
      bottom: "8px",
      left: "8px",
      width: "auto",
      maxWidth: "none",
      maxHeight: "min(55%, 520px)",
      padding: tokens.spacingHorizontalM,
      zIndex: 25,
    },
  },
  sidePanelScroll: {
    flex: 1,
    minHeight: 0,
    overflowX: "hidden",
    overflowY: "auto",
    overscrollBehavior: "contain",
    scrollbarGutter: "stable",
    paddingRight: tokens.spacingHorizontalS,
    touchAction: "pan-y",
  },
  section: {
    marginTop: tokens.spacingVerticalS,
    paddingTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    color: tokens.colorNeutralForeground1,
  },
  dangerButton: {
    marginTop: tokens.spacingVerticalS,
    width: "100%",
    color: tokens.colorStatusDangerForeground1,
  },
  footerHelp: {
    marginTop: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  predictOverlay: {
    position: "absolute",
    inset: 0,
    backgroundColor: "rgba(0, 0, 0, 0.45)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 2000,
  },
  predictDialog: {
    minWidth: "min(380px, calc(100vw - 32px))",
    maxWidth: "480px",
    padding: tokens.spacingHorizontalXXL,
    borderRadius: tokens.borderRadiusLarge,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow64,
  },
  mapInfo: {
    position: "absolute",
    bottom: "6px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 900,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground2,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    fontSize: tokens.fontSizeBase200,
    fontFamily: "monospace",
    whiteSpace: "nowrap",
    "@media (max-width: 700px)": {
      bottom: "calc(55% + 18px)",
      maxWidth: "calc(100% - 32px)",
      overflow: "hidden",
      textOverflow: "ellipsis",
    },
  },
});

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

// ── Uncertainty view ────────────────────────────────────────────────────────
// Colors every scored building by the model's predictive uncertainty (0 =
// confident, 1 = maximally uncertain). Stops match UNCERTAINTY_LEGEND_GRADIENT
// used by the panel legend. The driver reads the "unc" feature-state; buildings
// without a computed value coalesce to 0 (and are hidden by the opacity expr).
const UNCERTAINTY_STOPS = [
  [0, "#2c7bb6"],
  [0.25, "#abd9e9"],
  [0.5, "#ffffbf"],
  [0.75, "#fdae61"],
  [1, "#d7191c"],
];
const UNCERTAINTY_LEGEND_GRADIENT =
  "linear-gradient(to right, #2c7bb6, #abd9e9, #ffffbf, #fdae61, #d7191c)";
const UNCERTAINTY_FILL_OPACITY = 0.6;

function fillColorExprUncertainty() {
  return [
    "interpolate",
    ["linear"],
    ["coalesce", ["feature-state", "unc"], 0],
    ...UNCERTAINTY_STOPS.flat(),
  ];
}

// Only buildings with a computed "unc" value are painted; the rest stay
// transparent (coalesce sentinel -1 marks "no value").
function fillOpacityExprUncertainty() {
  return [
    "case",
    ["==", ["coalesce", ["feature-state", "unc"], -1], -1], 0,
    UNCERTAINTY_FILL_OPACITY,
  ];
}

// ── Misclassified view ──────────────────────────────────────────────────────
// A building is misclassified only when it has BOTH a human label and a
// current model prediction and those classes differ. The expression reads the
// same "label" and "pred" feature-state used by the existing views, so correct
// and unlabeled buildings remain transparent without a duplicate state map.
const MISCLASSIFIED_COLOR = "#D83B01";
const MISCLASSIFIED_FILL_OPACITY = 0.75;

function validClassStateExpr(stateKey) {
  return [
    "any",
    ["==", ["feature-state", stateKey], CLASS_INTACT],
    ["==", ["feature-state", stateKey], CLASS_DAMAGED],
    ["==", ["feature-state", stateKey], CLASS_CLOUDY],
  ];
}

function misclassifiedExpr() {
  return [
    "all",
    validClassStateExpr("label"),
    validClassStateExpr("pred"),
    ["!=", ["feature-state", "label"], ["feature-state", "pred"]],
  ];
}

function fillOpacityExprMisclassified() {
  return [
    "case",
    misclassifiedExpr(),
    MISCLASSIFIED_FILL_OPACITY,
    0,
  ];
}

// Normalized Shannon entropy of a probability vector, in [0, 1] (0 = a single
// class has all the mass, 1 = uniform across k classes). Used as the per-
// building uncertainty score for the uncertainty view.
function normalizedEntropy(probs) {
  const k = probs.length;
  if (k <= 1) return 0;
  let h = 0;
  for (const p of probs) if (p > 0) h -= p * Math.log(p);
  const norm = h / Math.log(k);
  return Math.max(0, Math.min(1, norm));
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

// Format a { mean, std } CV-metric block for the Advanced results table.
// asPercent=true renders precision/recall as "92 ± 3%"; otherwise (AUC) as
// two-decimal "0.92 ± 0.03". Returns an em-dash when the metric is undefined
// (mean == null, e.g. no fold produced a defined value).
function fmtMetric(m, asPercent) {
  if (!m || m.mean == null) return "—";
  if (asPercent) {
    return `${(m.mean * 100).toFixed(0)} ± ${(m.std * 100).toFixed(0)}%`;
  }
  return `${m.mean.toFixed(2)} ± ${m.std.toFixed(2)}`;
}

const InteractiveLabeler = () => {
  const styles = useStyles();
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
  // Guards asynchronous holdout/training work from publishing a model after
  // labels changed or were cleared while that work was in flight.
  const labelsRevisionRef = useRef(0);
  const fullPredictAbortRef = useRef({ cancelled: false });

  // Advanced → Swipe view. atlas.SwipeMap always reveals its SECONDARY map on
  // the RIGHT of the divider and shows its PRIMARY on the LEFT, so to land PRE
  // imagery on the left / POST imagery on the right we make the labeler map
  // (mapRef.current: post-event imagery + footprints + interaction) the
  // SECONDARY and a freshly-built pre-event map the PRIMARY. swipePreMapRef
  // holds that new pre-event map (created in swipeMapContainerRef), swipeRef
  // holds the atlas.SwipeMap that draws the divider, layerImageryRef caches the
  // layer's imagery URLs (resolved in createMap), and swipePmtilesUrlRef caches
  // the PMTiles archive URL so the pre map can draw the same building
  // footprints from the same source.
  const swipeMapContainerRef = useRef(null);
  const swipePreMapRef = useRef(null);
  const swipeRef = useRef(null);
  const layerImageryRef = useRef(null);
  const swipePmtilesUrlRef = useRef(null);

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
  // Advanced section: expand/collapse, 5-fold CV result + busy flag, swipe view.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [cvResult, setCvResult] = useState(null);
  const [cvRunning, setCvRunning] = useState(false);
  const [swipeOn, setSwipeOn] = useState(true);
  // Advanced → Uncertainty view: recolor every scored footprint by the model's
  // predictive uncertainty (with a legend).
  const [uncertaintyOn, setUncertaintyOn] = useState(false);
  // Advanced → Misclassified view: emphasize only human labels that disagree
  // with the current in-browser model prediction.
  const [misclassifiedOn, setMisclassifiedOn] = useState(false);

  // selectedClass / viewMode are read by long-lived map event handlers.
  const selectedClassRef = useRef(selectedClass);
  useEffect(() => {
    selectedClassRef.current = selectedClass;
  }, [selectedClass]);
  const viewModeRef = useRef(viewMode);
  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);
  // Read by long-lived map handlers (hydrateViewport) to decide whether to
  // compute per-building uncertainty on each viewport settle.
  const uncertaintyOnRef = useRef(uncertaintyOn);
  useEffect(() => {
    uncertaintyOnRef.current = uncertaintyOn;
  }, [uncertaintyOn]);
  const misclassifiedOnRef = useRef(misclassifiedOn);
  useEffect(() => {
    misclassifiedOnRef.current = misclassifiedOn;
  }, [misclassifiedOn]);
  // Read by the P hotkey (long-lived listener) so it can't switch to the
  // Predicted view before there are enough labels to train.
  const canTrainRef = useRef(false);

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
    // Cache the imagery URLs for the Advanced → Swipe view, which loads the
    // pre-event tiles onto its secondary map (falls back to satellite when
    // the layer has no pre-event imagery).
    layerImageryRef.current = layerData?.imagery || null;

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
      // Cache the PMTiles archive URL so the Advanced → Swipe pre map can draw
      // the same building footprints from the same source (see the swipe
      // effect below). Must match this source's `pmtiles://<url>` exactly so
      // both maps route through the same in-memory pmtiles handle.
      swipePmtilesUrlRef.current = browserPmtilesUrl;
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
        if (!isValidVector(vec)) continue;
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
        labelsRevisionRef.current += 1;
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

    // Predicted and Misclassified views both need current viewport
    // predictions. maybeTrainAndPredict reuses the cached model unless labels
    // changed.
    if (
      viewModeRef.current === "predict" ||
      misclassifiedOnRef.current
    ) {
      maybeTrainAndPredict(features);
    }

    // Uncertainty view — recolor the on-screen buildings by model uncertainty.
    if (uncertaintyOnRef.current) {
      computeUncertaintyForViewport(features);
    }
  }

  // Train (or reuse the cached model) and paint per-building uncertainty as the
  // "unc" feature-state for every building currently in the viewport. Shares
  // trainedModelRef with the predict path; returns silently (with a status
  // hint) when there aren't enough labels to train.
  function computeUncertaintyForViewport(features) {
    const entries = getValidLabeledEntries();
    const perClass = {};
    entries.forEach((e) => (perClass[e.label] = (perClass[e.label] || 0) + 1));
    const classesReady = Object.values(perClass).filter(
      (n) => n >= MIN_PER_CLASS
    ).length;
    if (classesReady < 2) {
      setStatus(
        `Need ${MIN_PER_CLASS}+ labels in at least 2 classes for uncertainty.`
      );
      return;
    }
    // Reuse the cached model unless the label set changed since it was trained.
    if (labelsDirtyRef.current || !trainedModelRef.current) {
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
    }
    const model = trainedModelRef.current;

    const ids = [];
    const matrix = [];
    const sources = [];
    for (const f of features) {
      if (f.id == null) continue;
      const vec = lookupFeatureVector(f.id);
      if (!isValidVector(vec)) continue;
      ids.push(f.id);
      matrix.push(vec);
      sources.push(f.source);
    }
    if (matrix.length === 0) return;
    const probs = model.predictProba(matrix);
    for (let i = 0; i < ids.length; i++) {
      const unc = normalizedEntropy(Object.values(probs[i]));
      setFeatureStateUnc(sources[i], ids[i], unc);
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
  function setFeatureStateUnc(sourceId, id, unc) {
    const gl = glMapRef.current;
    if (!gl) return;
    try {
      gl.setFeatureState(
        { source: sourceId, sourceLayer: PMTILES_SOURCE_LAYER, id },
        { unc }
      );
      mapRef.current?.triggerRepaint && mapRef.current.triggerRepaint();
    } catch (err) {
      console.warn("setFeatureState (unc) failed:", err);
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
    if (misclassifiedOn) {
      // The opacity expression itself requires a human label, a prediction,
      // and a class mismatch. Correct and unlabeled buildings stay clear.
      fill.setOptions({
        fillColor: MISCLASSIFIED_COLOR,
        fillOpacity: fillOpacityExprMisclassified(),
      });
      hydrateViewport(map);
    } else if (uncertaintyOn) {
      // Uncertainty view overrides the label/predict coloring entirely.
      fill.setOptions({
        fillColor: fillColorExprUncertainty(),
        fillOpacity: fillOpacityExprUncertainty(),
      });
      hydrateViewport(map);
    } else {
      fill.setOptions({
        fillColor: fillColorExpr(viewMode === "predict" ? "pred" : "label"),
        fillOpacity: fillOpacityExpr(viewMode === "predict" ? "pred" : "label"),
      });
      if (viewMode === "predict") hydrateViewport(map);
    }
    // hydrateViewport reads current refs and intentionally stays out of this
    // dependency list to avoid re-running the effect on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, uncertaintyOn, misclassifiedOn, isMapReady]);

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

  function getValidLabeledEntries() {
    return Object.values(labeledMapRef.current).filter((entry) =>
      isValidVector(entry.features)
    );
  }

  // ── Labeling ──────────────────────────────────────────────────────────────
  function recordLabel(id, props, cls) {
    const vec = lookupFeatureVector(id);
    if (!isValidVector(vec)) return false;
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
    labelsRevisionRef.current += 1;
    return true;
  }
  function labelBuilding(id, props, cls) {
    if (!recordLabel(id, props, cls)) return;
    setFeatureStateLabel(primarySourceId(), id, cls);
    refreshCounts();
    if (
      viewModeRef.current === "predict" ||
      uncertaintyOnRef.current ||
      misclassifiedOnRef.current
    ) {
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
    if (
      viewModeRef.current === "predict" ||
      uncertaintyOnRef.current ||
      misclassifiedOnRef.current
    ) {
      hydrateViewport(mapRef.current);
    }
  }
  function clearLabel(id) {
    const entry = labeledMapRef.current[id];
    if (entry) {
      delete savedLabelsRef.current[entry.overtureId ?? id];
    }
    delete labeledMapRef.current[id];
    labelsDirtyRef.current = true;
    labelsRevisionRef.current += 1;
    clearFeatureStateLabel(primarySourceId(), id);
    refreshCounts();
    if (
      viewModeRef.current === "predict" ||
      uncertaintyOnRef.current ||
      misclassifiedOnRef.current
    ) {
      hydrateViewport(mapRef.current);
    }
  }
  function refreshCounts() {
    const next = { 0: 0, 1: 0, 2: 0 };
    Object.values(labeledMapRef.current).forEach((e) => {
      next[e.label] = (next[e.label] || 0) + 1;
    });
    const nextCanTrain =
      [
        next[CLASS_INTACT],
        next[CLASS_DAMAGED],
        next[CLASS_CLOUDY],
      ].filter((count) => count >= MIN_PER_CLASS).length >= 2;
    canTrainRef.current = nextCanTrain;
    if (!nextCanTrain) {
      setUncertaintyOn(false);
      setMisclassifiedOn(false);
      setViewMode("label");
    }
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
    const entries = getValidLabeledEntries();
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
        const trainingRevision = labelsRevisionRef.current;
        setStatus("Training…");
        const nextMetrics = await holdoutMetricsDamaged(
          entries,
          0.2,
          CLASS_DAMAGED
        );
        const ovr = new OvRLogisticRegression({
          learningRate: 0.1,
          numSteps: 500,
          lambda: 0.01,
        });
        ovr.train(
          entries.map((e) => e.features),
          entries.map((e) => e.label)
        );
        if (trainingRevision !== labelsRevisionRef.current) {
          labelsDirtyRef.current = true;
          trainPendingRef.current = true;
          return;
        }
        if (nextMetrics) setMetrics({ ...nextMetrics, mode: "holdout" });
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
      if (shouldIgnoreShortcut(e)) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const key = e.key.toLowerCase();
      if (key === "1") setSelectedClass(CLASS_INTACT);
      else if (key === "2") setSelectedClass(CLASS_DAMAGED);
      else if (key === "3") setSelectedClass(CLASS_CLOUDY);
      else if (key === "t")
        setSelectedClass((c) => (c + 1) % 3);
      else if (key === "p") {
        // Predicted view needs a trained model; ignore until we have enough
        // labels (matches the disabled View toggle).
        if (!canTrainRef.current) return;
        const next = viewModeRef.current === "label" ? "predict" : "label";
        setViewMode(next);
        // Model-driven review views are mutually exclusive.
        if (next === "predict") {
          setUncertaintyOn(false);
          setMisclassifiedOn(false);
        }
      } else if (key === " " || e.code === "Space") {
        // preventDefault to stop the browser from scrolling the page
        // when the map container doesn't have focus.
        e.preventDefault();
        setShowFootprints((v) => !v);
      } else if (
        swipeRef.current &&
        (key === "a" || key === "s" || key === "d")
      ) {
        // Snap the swipe divider: 'a' = full left, 's' = middle, 'd' = full
        // right. sliderPosition is in pixels from the left of the map; the
        // SwipeMap module clamps out-of-range values to [0, width].
        const el = swipeMapContainerRef.current || mapContainerRef.current;
        const w = el ? el.getBoundingClientRect().width : 0;
        const pos = key === "a" ? 0 : key === "s" ? w / 2 : w;
        try {
          swipeRef.current.setOptions({ sliderPosition: pos });
        } catch (err) {
          console.warn("swipe setOptions (sliderPosition) failed:", err);
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // ── Advanced → 5-fold cross-validation ────────────────────────────────────
  // Runs stratified k-fold CV over the current labels via crossValidateMetrics.
  // It's CPU-bound, so crossValidateMetrics is async and yields between folds —
  // this keeps the main thread free enough that the map keeps rendering instead
  // of blanking out while the CV runs.
  async function handleRunCV() {
    const entries = getValidLabeledEntries();
    if (entries.length === 0) {
      setCvResult({ ok: false, reason: "Label some buildings first." });
      return;
    }
    setCvRunning(true);
    setCvResult(null);
    await new Promise((resolve) => setTimeout(resolve, 0));
    try {
      setCvResult(await crossValidateMetrics(entries, { k: 5 }));
    } catch (e) {
      console.error("Cross-validation failed:", e);
      setCvResult({
        ok: false,
        reason: `Cross-validation failed: ${e?.message || e}`,
      });
    } finally {
      setCvRunning(false);
    }
  }

  // ── Advanced → Swipe view (pre-event imagery reveal) ──────────────────────
  // Mirrors the Visualizer's swipe pattern (Visualizer.jsx:140-155, 466-467)
  // using the global atlas.SwipeMap loaded from
  // /assets/js/azure-maps-swipe-map.min.js in index.html — NOT an npm import.
  //
  // atlas.SwipeMap always clips its SECONDARY map to reveal it on the RIGHT of
  // the divider and shows its PRIMARY on the LEFT, and syncs both cameras on
  // every 'move'. To land PRE imagery on the left / POST imagery on the right
  // we therefore wire:
  //   • PRIMARY   = a freshly-built PRE-event map (created in
  //                 swipeMapContainerRef, the FIRST/behind map div), and
  //   • SECONDARY = the existing labeler map (mapRef.current: post-event
  //                 imagery + building footprints + click/label interaction),
  //                 which sits in the SECOND/on-top map div so its clipped
  //                 right half reveals the pre map underneath on the left.
  // The labeler map is ADOPTED as the secondary — SwipeMap only adds 'move' +
  // 'resize' handlers and clips its container, so an already-"ready" map
  // adopts cleanly and its own click/label/hydrate handlers are untouched. On
  // teardown we dispose ONLY the swipe control + the new pre map and clear the
  // clip SwipeMap left on the labeler's container; the labeler map itself is
  // never disposed here, so toggling swipe off/on repeatedly leaves the
  // labeler and its footprint interactions fully intact.
  useEffect(() => {
    if (!isMapReady || !swipeOn) return undefined;
    const labelerMap = mapRef.current;
    const container = swipeMapContainerRef.current;
    // Capture the labeler map's container node up front so the cleanup below
    // does not read a ref (mapContainerRef.current) that may have changed by
    // teardown — the node is stable for this effect's lifetime.
    const labelerContainer = mapContainerRef.current;
    if (!labelerMap || !container || !window.atlas || !window.atlas.SwipeMap) {
      return undefined;
    }

    // Seed the new pre map with the labeler's current camera so the two start
    // aligned before SwipeMap takes over camera synchronization.
    const cam = labelerMap.getCamera();
    const preMap = new window.atlas.Map(container, {
      center: cam.center,
      zoom: cam.zoom,
      bearing: cam.bearing || 0,
      pitch: cam.pitch || 0,
      maxPitch: 0,
      // Match the labeler map's style handling: "satellite" shows the Azure
      // aerial basemap in real deployments, while local docker dev (no Azure
      // Maps subscription) uses "blank" so the map control still fires "ready"
      // without a valid token. The pre-event TileLayer is added on top in
      // either case; with no pre-event imagery, loadImagery("") falls back to
      // the Azure satellite tileset (which renders once a real token exists).
      style: isAzureMapsPlaceholder ? "blank" : "satellite",
      language: "en-US",
      authOptions: getAzureMapsAuthOptions(),
    });
    swipePreMapRef.current = preMap;

    preMap.events.add("ready", () => {
      // Match the labeler map's interaction constraints (no rotate / pitch).
      preMap.setUserInteraction({
        dragRotateInteraction: false,
        scrollZoomInteraction: true,
        pinchZoomInteraction: true,
        pinchRotateInteraction: false,
      });
      // Pre-event imagery on the LEFT (primary) pane. loadImagery falls back to
      // the Azure satellite tileset when the tile URL is "" (no pre-event
      // imagery).
      const preUrl = layerImageryRef.current?.preEventTileUrl || "";
      loadImagery(
        toBrowserTitilerUrl(preUrl),
        preMap,
        { current: null },
        "swipePreEventLayer",
        true
      );

      // Draw the building footprints on the pre map too, from the SAME PMTiles
      // archive + styling helpers the labeler uses, so outlines (and the
      // unlabeled fill) span BOTH panes continuously — SwipeMap clips an entire
      // map, so a single footprint layer can only appear on one side.
      //
      // NOTE: per-building label colors are driven by feature-state on the
      // labeler's internal GL map (glMapRef), which this pre map does not have,
      // so footprints render here in the UNLABELED color while still showing
      // outlines. Per-building label colors currently render on the
      // post/interactive (right) pane only; mirroring feature-state across the
      // two GL maps would be a follow-up.
      if (swipePmtilesUrlRef.current) {
        try {
          preMap.sources.add(
            new window.atlas.source.VectorTileSource("buildings", {
              type: "vector",
              url: `pmtiles://${swipePmtilesUrlRef.current}`,
            })
          );
          preMap.layers.add(
            new window.atlas.layer.PolygonLayer("buildings", "swipeFill", {
              sourceLayer: PMTILES_SOURCE_LAYER,
              fillColor: UNLABELED_COLOR,
              fillOpacity: 0.15,
            })
          );
          preMap.layers.add(
            new window.atlas.layer.LineLayer("buildings", "swipeOutline", {
              sourceLayer: PMTILES_SOURCE_LAYER,
              strokeColor: "#1a5276",
              minZoom: 15,
              strokeWidth: ["step", ["zoom"], 1, 16, 2],
            })
          );
        } catch (e) {
          console.warn("Swipe pre-map footprints failed:", e);
        }
      }

      // Wire the native swipe control: PRIMARY = pre map (revealed on the
      // LEFT), SECONDARY = labeler map (clipped, revealed on the RIGHT).
      // atlas.SwipeMap keeps BOTH cameras in sync on every 'move' internally,
      // so we must NOT add our own camera-sync handler (doing so
      // double-updates the cameras and makes panning jump/stutter).
      try {
        swipeRef.current = new window.atlas.SwipeMap(preMap, labelerMap);
      } catch (e) {
        console.warn("atlas.SwipeMap init failed:", e);
      }
    });

    return () => {
      // Tear down the swipe control first — its dispose() removes the divider
      // handle it appended to the PRIMARY (pre map) container and detaches the
      // 'move'/'resize' sync handlers from BOTH maps — then dispose the new pre
      // map. The labeler map (mapRef.current / the SECONDARY) is deliberately
      // NOT disposed so its footprint interactions survive toggling swipe off.
      if (swipeRef.current) {
        try {
          if (typeof swipeRef.current.dispose === "function") {
            swipeRef.current.dispose();
          }
        } catch (e) {
          console.warn("atlas.SwipeMap dispose failed:", e);
        }
        swipeRef.current = null;
      }
      if (swipePreMapRef.current) {
        try {
          swipePreMapRef.current.dispose();
        } catch (e) {
          console.warn("swipe pre map dispose failed:", e);
        }
        swipePreMapRef.current = null;
      }
      // SwipeMap.dispose() does NOT clear the inline `clip` it set on the
      // SECONDARY (labeler) map's container, so clear it here or the labeler
      // stays clipped to its right half after swipe is turned off. Clear it on
      // both the element getMapContainer() reports and the div we passed to the
      // Map constructor, to be safe across Atlas builds.
      try {
        if (labelerMap && typeof labelerMap.getMapContainer === "function") {
          labelerMap.getMapContainer().style.clip = "";
        }
      } catch (e) {
        console.warn("clearing labeler map clip failed:", e);
      }
      if (labelerContainer) {
        labelerContainer.style.clip = "";
      }
      // Reset the pre map's container so the next toggle starts from a clean
      // slate (any leftover atlas DOM / clip is removed).
      container.style.clip = "";
      container.innerHTML = "";
    };
  }, [isMapReady, swipeOn]);

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
      savedLabelsRef.current = labels;
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
            labelsRevisionRef.current += 1;
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
    const entries = getValidLabeledEntries();
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
  // Predicted, Uncertainty, and Misclassified views need a trained model,
  // which needs at least MIN_PER_CLASS labels in 2+ classes.
  const canTrain =
    [
      counts[CLASS_INTACT],
      counts[CLASS_DAMAGED],
      counts[CLASS_CLOUDY],
    ].filter((count) => count >= MIN_PER_CLASS).length >= 2;

  return (
    <div className={styles.root}>
      <div
        className="labeling-tool-surface labeling-navigation-controls"
        style={{
          // While the swipe view is on, the "Pre imagery" label sits at the top
          // and the Back button drops just below it.
          top: swipeOn ? 46 : 10,
        }}
      >
        <Button
          id="backButton"
          appearance="transparent"
          icon={<FluentIcon name="ChevronLeft" />}
          onClick={() => navigate(-1)}
        >
          Back
        </Button>
      </div>

      {/* Map area: the labeler map plus the Advanced → Swipe view. Both map
          divs are absolutely positioned and fill this relative wrapper exactly
          (the same overlapping layout the Visualizer's swipe uses — see
          Visualizer.jsx + visualizer.css `.map`). atlas.SwipeMap reveals its
          SECONDARY on the RIGHT and shows its PRIMARY on the LEFT, so to land
          PRE imagery on the left / POST imagery on the right the PRE map
          (primary) must sit in the FIRST/behind div and the labeler map (post +
          footprints, secondary) in the SECOND/on-top div — its clipped right
          half then reveals the pre map underneath on the left. The divider
          handle (z-index:1, appended into the primary/pre container) still
          paints above both. The pre-map overlay stays display:none until the
          swipe toggle is on. */}
      <div style={{ position: "relative", flexGrow: 1 }}>
        {/* FIRST/behind: swipe PRIMARY = the new pre-event map (built on
            demand by the swipe effect while the toggle is on). */}
        <div
          ref={swipeMapContainerRef}
          id="interactiveLabelerSwipeMap"
          style={{
            position: "absolute",
            inset: 0,
            display: swipeOn ? "block" : "none",
          }}
        />
        {/* SECOND/on-top: the labeler map. When swipe is on it is adopted as
            the SwipeMap SECONDARY and clipped to its right half; when swipe is
            off it is the only visible map. */}
        <div
          ref={mapContainerRef}
          id="interactiveLabelerMap"
          style={{ position: "absolute", inset: 0 }}
        />

        {/* Pane labels, shown only while swipe is on. Rendered inside this
            relative wrapper so left/right map to the map area (not the window).
            "Pre imagery" sits at the very top-left (above the Back button, which
            drops to top:46 while swiping); "Post imagery" hugs the top-right
            corner. pointerEvents: none so they never intercept a divider
            drag. */}
        {swipeOn && (
          <>
            <div
              className={styles.mapBadge}
              style={{
                left: 10,
              }}
            >
              Pre imagery
            </div>
            <div
              className={`${styles.mapBadge} ${styles.mapBadgeRight}`}
            >
              Post imagery
            </div>
          </>
        )}

        {/* Legend, bottom-right of the map. Shows class colors normally, the
            uncertainty ramp, or the misclassified explanation. */}
        {isMapReady && showFootprints && (
          <div className={styles.legend}>
            {uncertaintyOn ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  Model uncertainty
                </div>
                <div
                  style={{
                    width: 130,
                    height: 10,
                    borderRadius: 3,
                    background: UNCERTAINTY_LEGEND_GRADIENT,
                  }}
                />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    color: tokens.colorNeutralForeground3,
                    marginTop: 2,
                  }}
                >
                  <span>Low (confident)</span>
                  <span>High</span>
                </div>
              </>
            ) : (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {viewMode === "predict" ? "Predicted" : "Labels"}
                </div>
                {CLASS_LABELS.map((name, i) => (
                  <div
                    key={name}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: 2,
                        background: CLASS_COLORS[i],
                        border: "1px solid rgba(0,0,0,0.25)",
                      }}
                    />
                    <span>{name}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {isMapReady && (
        <div className={`${styles.sidePanel} labeling-tool-surface`}>
          <div className={styles.sidePanelScroll}>
          <Text size={500} block style={{ marginBottom: 2 }}>
            Interactive Labeler
          </Text>
          {backend && (
            <div
              style={{
                fontSize: 11,
                color: backend === "WebGPU"
                  ? tokens.colorStatusSuccessForeground1
                  : tokens.colorNeutralForeground3,
                marginBottom: 8,
              }}
            >
              Compute: {backend}
            </div>
          )}

          <Field label="Set class">
            <RadioGroup
              value={String(selectedClass)}
              onChange={(_e, data) => setSelectedClass(parseInt(data.value, 10))}
            >
              {CLASS_OPTIONS.map((o) => (
                <Radio key={o.key} value={o.key} label={o.text} />
              ))}
            </RadioGroup>
          </Field>

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

          <Switch
            label="View: Predicted / Labeled"
            checked={viewMode === "predict"}
            disabled={!canTrain}
            onChange={(_e, data) => {
              setViewMode(data.checked ? "predict" : "label");
              // Model-driven review views are mutually exclusive.
              if (data.checked) {
                setUncertaintyOn(false);
                setMisclassifiedOn(false);
              }
            }}
            style={{ marginTop: 12 }}
          />
          {!canTrain && (
            <div className={styles.secondaryText} style={{ fontSize: 11, marginTop: -4 }}>
              Predicted / Uncertainty views need {MIN_PER_CLASS}+ labels in at
              least 2 classes.
            </div>
          )}

          <Switch
            label="Footprints"
            checked={showFootprints}
            onChange={(_e, data) => setShowFootprints(!!data.checked)}
          />

          {metrics && (
            <div className={styles.section} style={{ fontSize: 12 }}>
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
              <div className={styles.secondaryText} style={{ marginTop: 2 }}>
                {metrics.nPos} damaged / {metrics.nNeg} other
              </div>
            </div>
          )}

          <div
            className={styles.secondaryText}
            style={{
              marginTop: 8,
              minHeight: 18,
              fontSize: 12,
            }}
          >
            {status}
          </div>
          <div className={styles.secondaryText} style={{ marginTop: 4, fontSize: 12 }}>
            {totalLabeled} labeled · {viewportPredicted} predicted in viewport
          </div>

          <Button
            appearance="primary"
            disabled={isSaving || totalLabeled === 0}
            onClick={handleSaveLabels}
            style={{ marginTop: 16, width: "100%" }}
          >
            {isSaving ? "Saving…" : "Save labels"}
          </Button>
          <Button
            disabled={!!fullPredict || totalLabeled === 0}
            onClick={handlePredictAll}
            style={{ marginTop: 8, width: "100%" }}
            title="Run the trained model across every building in the layer (not just the viewport) and persist the predictions for the Validation / Assessment reports."
          >
            Predict all buildings
          </Button>
          <Button
            onClick={handleClearLabels}
            className={styles.dangerButton}
            title="Remove every label for this model — both in-session and in the saved store."
          >
            Clear labels
          </Button>

          {/* Advanced: expandable container for the 5-fold CV report and the
              swipe (pre-event) comparison view. */}
          <Button
            appearance="subtle"
            icon={<FluentIcon name={advancedOpen ? "ChevronDown" : "ChevronRight"} />}
            onClick={() => setAdvancedOpen((v) => !v)}
            style={{ marginTop: 12, paddingLeft: 0, height: 28 }}
          >
            Advanced
          </Button>

          {advancedOpen && (
            <div style={{ marginTop: 4 }}>
              <Button
                disabled={cvRunning || totalLabeled === 0}
                onClick={handleRunCV}
                style={{ width: "100%" }}
                title="Stratified 5-fold cross-validation of the in-browser model over your current labels. Reports per-class precision, recall, and one-vs-rest AUC as mean ± stdev across folds."
              >
                {cvRunning ? "Running…" : "Run 5-fold CV"}
              </Button>

              {cvRunning && (
                <div style={{ marginTop: 6 }}>
                  <Spinner
                    size="small"
                    label="Cross-validating…"
                    labelPosition="after"
                  />
                </div>
              )}

              {cvResult && !cvResult.ok && (
                <div
                  style={{ marginTop: 6, fontSize: 12, color: "#a4262c" }}
                >
                  {cvResult.reason}
                </div>
              )}

              {cvResult && cvResult.ok && (
                <div style={{ marginTop: 8, fontSize: 12 }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: 12,
                    }}
                  >
                    <thead>
                      <tr className={styles.secondaryText}>
                        <th style={{ textAlign: "left", padding: "2px 3px" }}>
                          Class
                        </th>
                        <th style={{ textAlign: "right", padding: "2px 3px" }}>
                          P
                        </th>
                        <th style={{ textAlign: "right", padding: "2px 3px" }}>
                          R
                        </th>
                        <th style={{ textAlign: "right", padding: "2px 3px" }}>
                          AUC
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {cvResult.classes.map((c) => {
                        const pc = cvResult.perClass[c];
                        return (
                          <tr key={c}>
                            <td
                              style={{
                                padding: "2px 3px",
                                color: CLASS_COLORS[c],
                                whiteSpace: "nowrap",
                              }}
                            >
                              {CLASS_LABELS[c] ?? `Class ${c}`}
                            </td>
                            <td
                              style={{
                                padding: "2px 3px",
                                textAlign: "right",
                              }}
                            >
                              {fmtMetric(pc.precision, true)}
                            </td>
                            <td
                              style={{
                                padding: "2px 3px",
                                textAlign: "right",
                              }}
                            >
                              {fmtMetric(pc.recall, true)}
                            </td>
                            <td
                              style={{
                                padding: "2px 3px",
                                textAlign: "right",
                              }}
                            >
                              {fmtMetric(pc.auc, false)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <div className={styles.secondaryText} style={{ marginTop: 4 }}>
                    k-fold={cvResult.k}
                    {cvResult.k < cvResult.requestedK &&
                      " (reduced — insufficient per-class samples)"}
                    {" · "}mean ± stdev across folds
                  </div>
                </div>
              )}

              <Divider style={{ marginTop: 12 }} />

              <Switch
                label="Swipe (pre-event)"
                checked={swipeOn}
                onChange={(_e, data) => setSwipeOn(!!data.checked)}
                style={{ marginTop: 12 }}
              />
              <div className={styles.secondaryText} style={{ fontSize: 11, marginTop: -4 }}>
                Drag the divider to compare pre-event imagery (left) with
                post-event imagery (right). Satellite basemap is used on the pre
                side when the layer has no pre-event imagery.
              </div>

              <Divider style={{ marginTop: 12 }} />

              <Switch
                label="Uncertainty view"
                checked={uncertaintyOn}
                disabled={!canTrain}
                onChange={(_e, data) => {
                  setUncertaintyOn(!!data.checked);
                  // Model-driven review views are mutually exclusive.
                  if (data.checked) {
                    setViewMode("label");
                    setMisclassifiedOn(false);
                  }
                }}
              />
              <div className={styles.secondaryText} style={{ fontSize: 11, marginTop: -4 }}>
                Recolors every scored footprint by the model&apos;s predictive
                uncertainty. Needs {MIN_PER_CLASS}+ labels in at least 2 classes.
                A legend appears on the map.
              </div>

              <Divider style={{ marginTop: 12 }} />

              <Switch
                label="Show misclassified buildings"
                checked={misclassifiedOn}
                disabled={!canTrain}
                onChange={(_e, data) => {
                  setMisclassifiedOn(!!data.checked);
                  if (data.checked) {
                    // Training is on demand: hydration trains/reuses the model
                    // and refreshes predictions for the visible buildings.
                    setViewMode("label");
                    setUncertaintyOn(false);
                    setStatus("Training model to find label disagreements…");
                  }
                }}
              />
              <div
                className={styles.secondaryText}
                style={{ fontSize: 11, marginTop: -4 }}
              >
                Trains or reuses the current model when enabled, then highlights
                only human-labeled buildings whose predicted class differs.
                Correct and unlabeled buildings stay unhighlighted.
              </div>
            </div>
          )}
          </div>

          <div className={styles.footerHelp}>
            <div style={{ marginBottom: 8 }}>
              Click a building to label it · right-click to clear it
            </div>
            <KeyboardShortcutHelp
              shortcuts={INTERACTIVE_LABELER_SHORTCUTS}
            />
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
        <div className={styles.predictOverlay}>
          <div className={styles.predictDialog}>
            <Text size={500} block style={{ marginBottom: 8 }}>
              Predict all buildings
            </Text>
            <div style={{ fontSize: 13, marginBottom: 12 }}>
              {fullPredict.message}
            </div>
            <ProgressBar
              value={
                fullPredict.phase === "predict" && fullPredict.total
                  ? fullPredict.current / fullPredict.total
                  : undefined
              }
            />
            <div
              style={{ marginTop: 14, display: "flex", justifyContent: "flex-end" }}
            >
              <Button
                onClick={cancelPredictAll}
                disabled={fullPredict.phase === "save"}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom info bar: lat / lon / zoom */}
      {isMapReady && (
        <div className={styles.mapInfo}>
          Zoom: {mapInfo.zoom.toFixed(2)} | Lat: {mapInfo.lat.toFixed(4)}, Lon:{" "}
          {mapInfo.lon.toFixed(4)}
        </div>
      )}
    </div>
  );
};

export default InteractiveLabeler;
