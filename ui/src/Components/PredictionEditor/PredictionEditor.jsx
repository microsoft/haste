// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Prediction Editor — review and edit a model's building-damage predictions,
// then save the result as a new version.
//
// Footprints stream from the model's PMTiles archive (kind=footprint_pmtiles)
// so the editor never downloads every polygon up front. The per-building
// scores come from a small JSON sidecar (kind=prediction_attrs) that is held
// in a ref; each building's class is derived in the browser from those scores
// plus the current thresholds, with any user edit taking precedence
// (predictionClassify.js owns that logic and is unit-tested). Colouring is
// applied as feature-state on the internal Mapbox-GL map keyed by the integer
// feature id, which is why moving the threshold slider recolours instantly
// with no server round-trip.
//
// Saving PUTs the thresholds plus the sparse override list to
// PutEditedPredictions, which writes a brand-new version — nothing is
// destructive.
//
// Both artifacts are produced by a queued job, so a model nobody has opened
// before arrives here unprepared. The editor enqueues that job itself
// (PutPreparePredictionTilesQueueMessage) and then polls the session until
// the artifacts exist, rather than telling the user to come back later — see
// the preparation effect below. The decisions behind that wait live in
// predictionPrep.js so they are unit-testable.
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Button,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  ProgressBar,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { PMTiles } from "pmtiles";
import { FluentIcon } from "../../util/icons";
import { apiGet, apiPut, buildUrl } from "../../util/api";
import {
  getPmtilesProtocol,
  InMemoryPMTilesSource,
  fetchArtifactBuffer,
} from "../../util/pmtiles.js";
import {
  getAzureMapsAuthOptions,
  isAzureMapsPlaceholder,
} from "../../util/azureMapsAuth";
import { AppContext } from "../../AppContext.jsx";
import { useTheme } from "../../util/ThemeContext.jsx";
import { shouldIgnoreShortcut } from "../keyboardShortcuts.js";
import PredictionEditorRightPanel from "./PredictionEditorRightPanel.jsx";
import {
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  FILTER_ALL,
  buildSavePayload,
  classifyAll,
  clearOverride,
  countClassChanges,
  cycleClass,
  filterIndices,
  indexById,
  matchesFilter,
  nextIndexInList,
  normalizeAttrs,
  setOverrideEntries,
  setOverrides,
} from "./predictionClassify.js";
import {
  MAX_PREP_POLL_ATTEMPTS,
  PREP_PHASE_FAILED,
  PREP_PHASE_REQUESTING,
  PREP_PHASE_TIMED_OUT,
  PREP_POLL_INTERVAL_MS,
  applyPrepResponse,
  buildPrepRequest,
  describeOutstandingArtifacts,
  evaluatePrepState,
  isPrepReady,
  nextPollAttempt,
  prepStateAfterPollError,
  prepStatusLabel,
  shouldPollPrep,
} from "./predictionPrep.js";
import "../../assets/css/drawingToolbar.css";

// Tippecanoe writes the buildings layer with `-l buildings`; every feature
// carries the integer `id` used for feature-state.
const PMTILES_SOURCE_LAYER = "buildings";
const SOURCE_ID = "predictionBuildings";
const FILL_LAYER_ID = "predictionFill";
const LINE_LAYER_ID = "predictionOutline";

// Paint expressions compare numbers, so each class gets a code.
const CLASS_CODES = {
  [CLASS_DAMAGED]: 1,
  [CLASS_NOT_DAMAGED]: 2,
  [CLASS_UNKNOWN]: 3,
};

// The map's colours come from the active Fluent theme rather than a hardcoded
// palette: `tokens.x` is the string "var(--x)", which the renderer cannot
// parse, so we resolve the custom property against a live element inside the
// FluentProvider subtree and hand the renderer the concrete value. Switching
// light/dark (or the brand palette) re-resolves them — see the theme effect.
const MAP_COLOR_TOKENS = {
  damaged: tokens.colorStatusDangerBackground3,
  notDamaged: tokens.colorStatusSuccessBackground3,
  unknown: tokens.colorNeutralForeground3,
  pending: tokens.colorNeutralBackground5,
  outline: tokens.colorNeutralStrokeAccessible,
  edited: tokens.colorBrandStroke1,
  selected: tokens.colorNeutralForeground1,
};

// Last-resort values, used only if a custom property cannot be resolved (the
// renderer needs *some* parseable colour or the layer fails to paint). Named
// CSS colours, deliberately not theme-specific hex codes.
const FALLBACK_COLORS = {
  damaged: "firebrick",
  notDamaged: "seagreen",
  unknown: "dimgray",
  pending: "lightgray",
  outline: "steelblue",
  edited: "royalblue",
  selected: "white",
};

function resolveThemeColors(element) {
  const style = element ? window.getComputedStyle(element) : null;
  const colors = {};
  for (const [key, tokenValue] of Object.entries(MAP_COLOR_TOKENS)) {
    const match = /var\((--[^,)]+)/.exec(String(tokenValue));
    const resolved =
      match && style ? style.getPropertyValue(match[1]).trim() : "";
    colors[key] = resolved || FALLBACK_COLORS[key];
  }
  return colors;
}

function fillColorExpression(colors) {
  return [
    "case",
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_DAMAGED]],
    colors.damaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_NOT_DAMAGED]],
    colors.notDamaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_UNKNOWN]],
    colors.unknown,
    colors.pending,
  ];
}

// Buildings filtered out stay on screen as context, but faint.
const FILL_OPACITY_EXPRESSION = [
  "case",
  ["==", ["feature-state", "dim"], true],
  0.1,
  0.55,
];

function strokeColorExpression(colors) {
  return [
    "case",
    ["==", ["feature-state", "selected"], true],
    colors.selected,
    ["==", ["feature-state", "edited"], true],
    colors.edited,
    colors.outline,
  ];
}

const STROKE_WIDTH_EXPRESSION = [
  "case",
  ["==", ["feature-state", "selected"], true],
  4,
  ["==", ["feature-state", "edited"], true],
  2.5,
  1,
];

// atlas.Map has no public setFeatureState; the renderer underneath (a
// Mapbox-GL fork) does. Same duck-typed scan the Interactive Labeler uses.
function findGlMap(atlasMap) {
  const direct = [atlasMap.map, atlasMap._map, atlasMap.gl, atlasMap._gl];
  for (const candidate of direct) {
    if (candidate && typeof candidate.setFeatureState === "function") {
      return candidate;
    }
  }
  for (const key of Object.keys(atlasMap)) {
    const value = atlasMap[key];
    if (value && typeof value === "object" && typeof value.setFeatureState === "function") {
      return value;
    }
  }
  return null;
}

// Average of the first ring's vertices — good enough to centre the camera on
// a building, and far cheaper than a real centroid.
function featureCentroid(geometry) {
  if (!geometry) return null;
  const ring =
    geometry.type === "Polygon"
      ? geometry.coordinates?.[0]
      : geometry.type === "MultiPolygon"
        ? geometry.coordinates?.[0]?.[0]
        : null;
  if (!Array.isArray(ring) || ring.length === 0) return null;
  let lng = 0;
  let lat = 0;
  for (const position of ring) {
    lng += position[0];
    lat += position[1];
  }
  return [lng / ring.length, lat / ring.length];
}

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexGrow: 1,
    minHeight: 0,
    position: "relative",
    isolation: "isolate",
    overflow: "hidden",
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  map: {
    flexGrow: 1,
    minHeight: 0,
  },
  messageCard: {
    position: "absolute",
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
    zIndex: 1000,
    boxSizing: "border-box",
    width: "min(520px, calc(100% - 32px))",
    padding: tokens.spacingHorizontalXXL,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalS,
    textAlign: "center",
    alignItems: "center",
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow16,
  },
  messageBody: {
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
  },
  messageDetail: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    wordBreak: "break-word",
  },
  // Preparation card: status line, indeterminate progress, and actions. All
  // colours come from Fluent tokens so the card is readable in either theme.
  messageActions: {
    marginTop: tokens.spacingVerticalS,
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: tokens.spacingHorizontalS,
  },
  messageBar: {
    width: "100%",
    textAlign: "left",
  },
  prepProgress: {
    width: "100%",
  },
  prepStatusRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "center",
    gap: tokens.spacingHorizontalXS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
  },
  prepStatusValue: {
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusCircular,
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground4,
    fontWeight: tokens.fontWeightSemibold,
  },
  legend: {
    position: "absolute",
    right: "calc(clamp(300px, 25vw, 360px) + 20px)",
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
  legendRow: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
  },
  legendSwatch: {
    width: "12px",
    height: "12px",
    borderRadius: tokens.borderRadiusSmall,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  // Legend swatches read the same tokens the map palette resolves at
  // runtime, so the two can never drift apart.
  legendDamaged: {
    backgroundColor: tokens.colorStatusDangerBackground3,
  },
  legendNotDamaged: {
    backgroundColor: tokens.colorStatusSuccessBackground3,
  },
  legendUnknown: {
    backgroundColor: tokens.colorNeutralForeground3,
  },
  legendTitle: {
    marginBottom: tokens.spacingVerticalXXS,
    fontWeight: tokens.fontWeightSemibold,
  },
  selectBox: {
    position: "absolute",
    display: "none",
    zIndex: 900,
    pointerEvents: "none",
    border: `${tokens.strokeWidthThick} dashed ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
    opacity: 0.4,
  },
  mapHint: {
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
    fontSize: tokens.fontSizeBase100,
    whiteSpace: "nowrap",
    pointerEvents: "none",
    "@media (max-width: 700px)": {
      display: "none",
    },
  },
});

// Load phases rendered explicitly, so a not-yet-built artifact shows an
// explanation instead of an empty map. PHASE_PREPARING covers the whole
// enqueue-and-wait cycle; the detail inside it (queued / running / failed /
// gave up) lives in `prepState`.
const PHASE_LOADING = "loading";
const PHASE_READY = "ready";
const PHASE_PREPARING = "preparing";
const PHASE_EMPTY = "empty";
const PHASE_ERROR = "error";

const PredictionEditor = () => {
  const styles = useStyles();
  const { projectId, imageLayerId, modelId } = useParams();
  const navigate = useNavigate();
  const { setIsLoading, setDialog } = useContext(AppContext);
  const { isDark, palette } = useTheme();

  // ── Refs ──────────────────────────────────────────────────────────────────
  const rootRef = useRef(null);
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const glMapRef = useRef(null);
  const fillLayerRef = useRef(null);
  const lineLayerRef = useRef(null);
  const internalLayerIdsRef = useRef([]);
  // The prediction sidecar, held in a ref: the arrays never change after load
  // and can be large, so they stay out of React state. `attrsVersion` below
  // is what tells the render tree they arrived.
  const attrsRef = useRef(null);
  const indexByIdRef = useRef(new Map());
  // The renderer renames our source internally; the first rendered feature
  // tells us what it actually calls it, which is the id feature-state writes
  // must use for buildings that are not part of a query result.
  const primarySourceIdRef = useRef(SOURCE_ID);
  const hydrateTimerRef = useRef(null);
  // Set by Prev/Next only: clicking a footprint should not yank the camera.
  const pendingPanRef = useRef(false);
  // Mirrors of state that long-lived map handlers read (a handler registered
  // in the map's "ready" callback closes over the first render's values).
  const classesRef = useRef([]);
  const editedRef = useRef([]);
  const overridesRef = useRef({});
  const filterRef = useRef(FILTER_ALL);
  const clickActionRef = useRef("cycle");
  const colorsRef = useRef(FALLBACK_COLORS);
  // id -> [lng, lat], harvested from rendered footprints. The sidecar carries
  // no geometry, so this is the only way Prev/Next knows where to pan.
  const centroidsRef = useRef(new Map());
  const selectedIdRef = useRef(null);
  const boxRef = useRef(null);
  const boxCleanupRef = useRef(null);
  // Guards every setState that happens after an await, so nothing writes to a
  // torn-down component (and, with it, no timer outlives the editor).
  const mountedRef = useRef(true);
  // Incremented every time the route params change. Async work captures the id it
  // started under and drops its results if a newer run has taken over, so a
  // fast model switch cannot have the old model's session clobber the new
  // one's (the component stays mounted across that switch, so mountedRef
  // alone would not catch it).
  const initRunRef = useRef(0);
  // Latest session, for the async prep helpers: they run outside the render
  // that produced `session` and must not merge into a stale copy.
  const sessionRef = useRef(null);

  // ── State ─────────────────────────────────────────────────────────────────
  const [phase, setPhase] = useState(PHASE_LOADING);
  const [errorMessage, setErrorMessage] = useState("");
  const [session, setSession] = useState(null);
  const [attrsVersion, setAttrsVersion] = useState(0);
  // Azure Maps builds its source/layers inside the async "ready" handler,
  // which fires AFTER createMap() resolves. Mirroring readiness in state (and
  // depending on it below) is what makes the styling effects re-run once the
  // layers actually exist — the refs alone never trigger a render.
  const [isSourceReady, setIsSourceReady] = useState(false);

  const [threshold, setThreshold] = useState(0.5);
  const [unknownThreshold, setUnknownThreshold] = useState(0);
  // What the current thresholds are compared against for the "N buildings
  // would change class" readout: the model default at first, then whatever
  // was last saved.
  const [baseline, setBaseline] = useState({
    threshold: 0.5,
    unknownThreshold: 0,
  });
  const [overrides, setOverridesState] = useState({});
  const [classification, setClassification] = useState(null);
  const [changeCount, setChangeCount] = useState(0);
  const [filter, setFilter] = useState(FILTER_ALL);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [clickAction, setClickAction] = useState("cycle");

  const [versions, setVersions] = useState([]);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [savedResult, setSavedResult] = useState(null);

  // Preparation wait-state, shaped by predictionPrep.js:
  // { phase, status, statusMessage, attempt, error }. Null once the artifacts
  // are in hand (or when they were ready from the start).
  const [prepState, setPrepState] = useState(null);
  // Bumped to hand the artifact + map load to its own effect. Doing the load
  // in an effect rather than inline guarantees React has already committed
  // the render that mounts the map container, so mapContainerRef.current is
  // a real element — the editor may reach this point from the preparing card,
  // where the container was not in the DOM at all.
  const [loadToken, setLoadToken] = useState(0);

  // ── Ref mirrors ───────────────────────────────────────────────────────────
  useEffect(() => {
    overridesRef.current = overrides;
  }, [overrides]);
  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);
  useEffect(() => {
    clickActionRef.current = clickAction;
  }, [clickAction]);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  // Mount flag. Set in an effect (not just at ref creation) so a remount —
  // React StrictMode double-invokes effects in development — flips it back on.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // The session URL is stable for a route; both the initial load and every
  // poll go through it.
  const sessionEndpoint = useMemo(
    () =>
      `GetPredictionEditSession?projectId=${encodeURIComponent(projectId)}` +
      `&imageLayerId=${encodeURIComponent(imageLayerId)}` +
      `&modelId=${encodeURIComponent(modelId)}`,
    [projectId, imageLayerId, modelId]
  );

  // Adopt a freshly fetched session: keep the version history in sync and
  // hand the object to the prep helpers through the ref.
  const adoptSession = useCallback((editSession) => {
    sessionRef.current = editSession;
    setSession(editSession);
    if (Array.isArray(editSession?.versions)) setVersions(editSession.versions);
  }, []);

  // True when the component is gone, or when a newer route run has taken
  // over. Every async continuation checks this before touching state.
  const isStale = useCallback(
    (runId) => !mountedRef.current || runId !== initRunRef.current,
    []
  );

  // Artifacts exist: show the map container (PHASE_LOADING) and let the load
  // effect do the fetching, one committed render later.
  const startArtifactLoad = useCallback(() => {
    setPrepState(null);
    setPhase(PHASE_LOADING);
    setLoadToken((token) => token + 1);
  }, []);

  // ── Preparation ───────────────────────────────────────────────────────────
  // Enqueue the job that builds the PMTiles archive and the score sidecar.
  // Called once on open when the artifacts are missing, and again (with
  // force) from the Retry action after a terminal failure. Without this the
  // editor would just sit on "still being prepared" forever, because nothing
  // else in the app ever queues that job.
  const requestPreparation = useCallback(
    async (force = false) => {
      const runId = initRunRef.current;
      setPhase(PHASE_PREPARING);
      setPrepState({
        phase: PREP_PHASE_REQUESTING,
        status: "",
        statusMessage: "",
        attempt: 0,
        error: "",
      });
      try {
        const response = await apiPut(
          "PutPreparePredictionTilesQueueMessage",
          buildPrepRequest({ projectId, imageLayerId, modelId, force })
        );
        if (isStale(runId)) return;
        // The response carries the same readiness flags as the session, so a
        // job that had already finished opens the editor immediately instead
        // of waiting out a poll interval.
        const merged = applyPrepResponse(sessionRef.current, response);
        adoptSession(merged);
        const decision = evaluatePrepState(merged, 0, MAX_PREP_POLL_ATTEMPTS);
        if (decision.ready) {
          startArtifactLoad();
          return;
        }
        setPrepState(decision);
      } catch (error) {
        if (isStale(runId)) return;
        console.error("Could not queue prediction tile preparation:", error);
        setPrepState({
          phase: PREP_PHASE_FAILED,
          status: "",
          statusMessage: "",
          attempt: 0,
          error:
            error?.message ||
            "The preparation job could not be queued. Try again.",
        });
      }
    },
    [projectId, imageLayerId, modelId, adoptSession, startArtifactLoad, isStale]
  );

  // ── Load: session -> (prepare) -> attributes -> map ───────────────────────
  useEffect(() => {
    let cancelled = false;
    const runId = initRunRef.current + 1;
    initRunRef.current = runId;

    const init = async () => {
      setIsLoading(true, "Loading Prediction Editor");
      // Route params can change without remounting; start from a clean slate.
      setPhase(PHASE_LOADING);
      setPrepState(null);
      setIsSourceReady(false);
      setOverridesState({});
      setClassification(null);
      setSelectedIndex(-1);
      setSavedResult(null);
      setSaveError("");
      setVersions([]);
      attrsRef.current = null;
      centroidsRef.current = new Map();
      selectedIdRef.current = null;
      try {
        const editSession = await apiGet(sessionEndpoint);
        if (cancelled || isStale(runId)) return;
        adoptSession(editSession);

        // Start from the model's own operating point so the first paint
        // matches what the rest of the app already shows for this model.
        const startThreshold =
          typeof editSession?.defaultThreshold === "number" &&
          Number.isFinite(editSession.defaultThreshold)
            ? editSession.defaultThreshold
            : 0.5;
        setThreshold(startThreshold);
        setUnknownThreshold(0);
        setBaseline({ threshold: startThreshold, unknownThreshold: 0 });

        if (!(Number(editSession?.buildingCount) > 0)) {
          setPhase(PHASE_EMPTY);
          return;
        }
        if (isPrepReady(editSession)) {
          startArtifactLoad();
          return;
        }
        // Nothing else queues this job, so the editor does it — once, without
        // force, then waits on the poll effect below.
        await requestPreparation(false);
      } catch (error) {
        if (cancelled || isStale(runId)) return;
        console.error("Error initializing the prediction editor:", error);
        setErrorMessage(
          error?.message || "The prediction editor could not be loaded."
        );
        setPhase(PHASE_ERROR);
      } finally {
        // Release the app-wide spinner unless a newer run has taken it over
        // (that run turns it off itself). Safe after unmount: the flag lives
        // in AppContext, above this component, so an editor torn down
        // mid-load cannot leave the whole app behind an overlay.
        if (runId === initRunRef.current) setIsLoading(false);
      }
    };

    init();

    return () => {
      cancelled = true;
      teardownMap();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, imageLayerId, modelId]);

  // Poll the session while the prep job runs, and open the editor the moment
  // both artifacts land — no page reload.
  //
  // Each pass schedules exactly ONE timeout and then re-runs off the state it
  // wrote, so there is never more than one timer in flight and never two
  // overlapping requests. The cleanup clears that timer, which is what stops
  // polling on unmount and on a route change; `mountedRef` covers the request
  // that is already in the air when the component goes away.
  useEffect(() => {
    if (!shouldPollPrep(prepState?.phase)) return undefined;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const runId = initRunRef.current;
      try {
        const editSession = await apiGet(sessionEndpoint);
        if (cancelled || isStale(runId)) return;
        adoptSession(editSession);
        const decision = evaluatePrepState(
          editSession,
          nextPollAttempt(prepState.attempt),
          MAX_PREP_POLL_ATTEMPTS
        );
        if (decision.ready) {
          startArtifactLoad();
          return;
        }
        setPrepState(decision);
      } catch (error) {
        if (cancelled || isStale(runId)) return;
        // A blip in the API must not abandon a healthy job; keep the last
        // known status and count the attempt against the cap.
        setPrepState((previous) =>
          prepStateAfterPollError(
            previous,
            error?.message,
            MAX_PREP_POLL_ATTEMPTS
          )
        );
      }
    }, PREP_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [prepState, sessionEndpoint, adoptSession, startArtifactLoad, isStale]);

  // ── Load the artifacts and build the map ──────────────────────────────────
  // Runs only when startArtifactLoad() bumps the token, i.e. after a render
  // in which the map container is mounted.
  useEffect(() => {
    if (!loadToken) return undefined;
    let cancelled = false;
    const runId = initRunRef.current;

    const load = async () => {
      setIsLoading(true, "Loading predictions");
      setIsSourceReady(false);
      try {
        const attrs = await loadAttributes();
        if (cancelled || isStale(runId)) return;
        attrsRef.current = attrs;
        indexByIdRef.current = indexById(attrs);
        setAttrsVersion((version) => version + 1);

        if (!window.atlas) {
          throw new Error(
            "The Azure Maps control did not load, so footprints cannot be shown."
          );
        }
        await createMap();
        if (cancelled || isStale(runId)) {
          // The editor went away (or moved to another model) while the
          // archive was downloading; the map this call just built would
          // otherwise never be disposed.
          teardownMap();
          return;
        }
        setPhase(PHASE_READY);
      } catch (error) {
        if (cancelled || isStale(runId)) return;
        console.error("Error initializing the prediction editor:", error);
        setErrorMessage(
          error?.message || "The prediction editor could not be loaded."
        );
        setPhase(PHASE_ERROR);
      } finally {
        // Same rule as the init effect: whoever still owns the run clears the
        // app-wide spinner.
        if (runId === initRunRef.current) setIsLoading(false);
      }
    };

    load();

    return () => {
      cancelled = true;
      teardownMap();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadToken]);

  // Single owner of map teardown, called from both load effects' cleanups:
  // whichever runs first nulls the refs, so a double call is a no-op.
  function teardownMap() {
    // Read at teardown on purpose: the box-select listeners are registered
    // well after the effect that owns them runs.
    if (boxCleanupRef.current) {
      boxCleanupRef.current();
      boxCleanupRef.current = null;
    }
    if (hydrateTimerRef.current) {
      clearTimeout(hydrateTimerRef.current);
      hydrateTimerRef.current = null;
    }
    if (mapRef.current) {
      mapRef.current.dispose();
      mapRef.current = null;
    }
    glMapRef.current = null;
    fillLayerRef.current = null;
    lineLayerRef.current = null;
  }

  async function loadAttributes() {
    // Streamed through the same-origin API proxy (managed identity server
    // side) so remote analysts behind the storage firewall can read it.
    const url = buildUrl(
      `GetModelArtifact?projectId=${encodeURIComponent(projectId)}` +
        `&modelId=${encodeURIComponent(modelId)}&kind=prediction_attrs`
    );
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(
        `Failed to load prediction attributes (HTTP ${response.status}).`
      );
    }
    const attrs = normalizeAttrs(await response.json());
    if (attrs.n === 0) {
      throw new Error("The prediction attributes file contains no buildings.");
    }
    return attrs;
  }

  async function createMap() {
    const protocol = getPmtilesProtocol();
    const archiveUrl = buildUrl(
      `GetModelArtifact?projectId=${encodeURIComponent(projectId)}` +
        `&modelId=${encodeURIComponent(modelId)}&kind=footprint_pmtiles`
    );

    // Download the whole archive once and serve pmtiles.js from memory: the
    // SWA /api proxy in front of the function app does not honour range
    // requests.
    const buffer = await fetchArtifactBuffer(archiveUrl);
    const archive = new PMTiles(new InMemoryPMTilesSource(archiveUrl, buffer));
    if (protocol) protocol.add(archive);
    const header = await archive.getHeader();

    let initialCamera = { center: [0, 0], zoom: 3 };
    if (header) {
      const hasCenter = header.centerLon != null && header.centerLat != null;
      const centerLon = hasCenter
        ? header.centerLon
        : (header.minLon + header.maxLon) / 2;
      const centerLat = hasCenter
        ? header.centerLat
        : (header.minLat + header.maxLat) / 2;
      initialCamera = {
        center: [centerLon, centerLat],
        zoom: header.centerZoom || Math.max(10, (header.maxZoom || 14) - 1),
      };
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

      const source = new window.atlas.source.VectorTileSource(SOURCE_ID, {
        type: "vector",
        url: `pmtiles://${archiveUrl}`,
        // Azure Maps ignores promoteId, but the tiles already carry native
        // integer feature ids (tippecanoe --use-attribute-for-id=id), which
        // is what setFeatureState needs.
        promoteId: { [PMTILES_SOURCE_LAYER]: "id" },
      });
      map.sources.add(source);

      const paint = colorsRef.current;
      const fillLayer = new window.atlas.layer.PolygonLayer(
        SOURCE_ID,
        FILL_LAYER_ID,
        {
          sourceLayer: PMTILES_SOURCE_LAYER,
          fillColor: fillColorExpression(paint),
          fillOpacity: FILL_OPACITY_EXPRESSION,
        }
      );
      map.layers.add(fillLayer);
      fillLayerRef.current = fillLayer;

      const lineLayer = new window.atlas.layer.LineLayer(
        SOURCE_ID,
        LINE_LAYER_ID,
        {
          sourceLayer: PMTILES_SOURCE_LAYER,
          strokeColor: strokeColorExpression(paint),
          strokeWidth: STROKE_WIDTH_EXPRESSION,
        }
      );
      map.layers.add(lineLayer);
      lineLayerRef.current = lineLayer;

      const glMap = findGlMap(map);
      glMapRef.current = glMap;
      if (glMap && typeof glMap.getStyle === "function") {
        // Azure Maps renames our source/layer internally; discover the ids
        // the renderer actually uses so queryRenderedFeatures can target them.
        try {
          const style = glMap.getStyle();
          const sourceIds = Object.keys(style.sources || {});
          const ours = [
            SOURCE_ID,
            ...sourceIds.filter((s) => s === SOURCE_ID || /predict|build/i.test(s)),
            ...sourceIds,
          ];
          internalLayerIdsRef.current = (style.layers || [])
            .filter(
              (layer) =>
                layer.type === "fill" &&
                (ours.includes(layer.source) || /predict|build/i.test(layer.id))
            )
            .map((layer) => layer.id);
        } catch (error) {
          console.warn("glMap.getStyle() failed:", error);
        }
      }

      map.events.add("click", fillLayer, (event) => {
        // Ctrl+click starts a box-select drag; don't also toggle a class.
        if (
          event.originalEvent &&
          (event.originalEvent.ctrlKey || event.originalEvent.metaKey)
        ) {
          return;
        }
        const feature = featureAtEvent(map, event);
        if (feature) handleFeatureClick(feature.id);
      });
      map.events.add("contextmenu", fillLayer, (event) => {
        const feature = featureAtEvent(map, event);
        if (feature) handleClearOverrideForId(feature.id);
        return false;
      });
      map.getCanvasContainer().style.cursor = "pointer";
      setupBoxSelect(map);

      const hydrate = () => scheduleHydrate();
      map.events.add("moveend", hydrate);
      map.events.add("sourcedata", (event) => {
        if (event && event.isSourceLoaded) hydrate();
      });
      hydrateViewport();
      setIsSourceReady(true);
    });

    mapRef.current = map;
  }

  // ── Renderer helpers (all read refs so map handlers stay valid) ───────────
  function featureAtEvent(map, event) {
    const glMap = glMapRef.current;
    if (!glMap) return null;
    let pixel = event.pixel;
    if (!pixel && event.position) {
      const pixels = map.positionsToPixels([event.position]);
      pixel = pixels && pixels[0];
    }
    if (!pixel) return null;
    try {
      const layerIds = internalLayerIdsRef.current;
      const rendered = glMap.queryRenderedFeatures(
        pixel,
        layerIds && layerIds.length ? { layers: layerIds } : undefined
      );
      const feature = rendered && rendered[0];
      if (!feature || feature.id == null) return null;
      return { id: feature.id, source: feature.source };
    } catch (error) {
      console.warn("queryRenderedFeatures failed:", error);
      return null;
    }
  }

  function renderedFeatures(box) {
    const glMap = glMapRef.current;
    if (!glMap) return [];
    const layerIds = internalLayerIdsRef.current;
    try {
      return (
        glMap.queryRenderedFeatures(
          box,
          layerIds && layerIds.length ? { layers: layerIds } : undefined
        ) || []
      );
    } catch (error) {
      console.warn("queryRenderedFeatures (viewport) failed:", error);
      return [];
    }
  }

  function writeFeatureState(sourceId, id, state) {
    const glMap = glMapRef.current;
    if (!glMap) return;
    try {
      glMap.setFeatureState(
        {
          source: sourceId || primarySourceIdRef.current || SOURCE_ID,
          sourceLayer: PMTILES_SOURCE_LAYER,
          id,
        },
        state
      );
    } catch (error) {
      console.warn("feature-state write failed:", error);
    }
  }

  // Tile loads and camera moves arrive in bursts; coalesce them so a pan
  // costs one queryRenderedFeatures pass rather than a dozen.
  function scheduleHydrate() {
    if (hydrateTimerRef.current) return;
    hydrateTimerRef.current = setTimeout(() => {
      hydrateTimerRef.current = null;
      hydrateViewport();
    }, 120);
  }

  // Paint every footprint currently on screen from the cached classification,
  // and remember where each one is so Prev/Next can pan to it. Called on every
  // viewport settle and whenever the classification changes.
  function hydrateViewport() {
    const features = renderedFeatures(undefined);
    if (features.length === 0) return;
    const classes = classesRef.current;
    const edited = editedRef.current;
    const byId = indexByIdRef.current;
    const activeFilter = filterRef.current;
    const selectedId = selectedIdRef.current;
    for (const feature of features) {
      const id = feature.id;
      if (id == null) continue;
      if (feature.source) primarySourceIdRef.current = feature.source;
      const index = byId.get(id);
      if (index === undefined) continue;
      if (!centroidsRef.current.has(id)) {
        const centroid = featureCentroid(feature.geometry);
        if (centroid) centroidsRef.current.set(id, centroid);
      }
      const cls = classes[index];
      writeFeatureState(feature.source, id, {
        cls: CLASS_CODES[cls] || 0,
        dim: !matchesFilter(cls, edited[index], activeFilter),
        edited: !!edited[index],
        selected: selectedId === id,
      });
    }
    if (mapRef.current && mapRef.current.triggerRepaint) {
      mapRef.current.triggerRepaint();
    }
  }

  // ── Editing ───────────────────────────────────────────────────────────────
  function handleFeatureClick(id) {
    const index = indexByIdRef.current.get(id);
    if (index === undefined) return;
    setSelectedIndex(index);
    const action = clickActionRef.current;
    const cls =
      action === "cycle" ? cycleClass(classesRef.current[index]) : action;
    setOverridesState((previous) => setOverrides(previous, [id], cls));
  }

  function handleClearOverrideForId(id) {
    const index = indexByIdRef.current.get(id);
    if (index === undefined) return;
    setSelectedIndex(index);
    setOverridesState((previous) => clearOverride(previous, id));
  }

  function applyClickActionToIds(ids) {
    if (ids.length === 0) return;
    const action = clickActionRef.current;
    if (action !== "cycle") {
      setOverridesState((previous) => setOverrides(previous, ids, action));
      return;
    }
    // Cycle mode over a box: advance each building from its own class.
    const classes = classesRef.current;
    const byId = indexByIdRef.current;
    const entries = ids
      .map((id) => {
        const index = byId.get(id);
        if (index === undefined) return null;
        return { id, class: cycleClass(classes[index]) };
      })
      .filter(Boolean);
    setOverridesState((previous) => setOverrideEntries(previous, entries));
  }

  function setClassForSelected(cls) {
    const attrs = attrsRef.current;
    if (!attrs || selectedIndex < 0 || selectedIndex >= attrs.n) return;
    const id = attrs.ids[selectedIndex];
    setOverridesState((previous) => setOverrides(previous, [id], cls));
  }

  function clearSelectedOverride() {
    const attrs = attrsRef.current;
    if (!attrs || selectedIndex < 0 || selectedIndex >= attrs.n) return;
    setOverridesState((previous) =>
      clearOverride(previous, attrs.ids[selectedIndex])
    );
  }

  function clearAllOverrides() {
    setOverridesState({});
  }

  // ── Ctrl+drag box-select ──────────────────────────────────────────────────
  function setupBoxSelect(map) {
    const canvas = map.getCanvasContainer();
    let origin = null;

    const onDown = (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      event.stopPropagation();
      map.setUserInteraction({ dragPanInteraction: false });
      const rect = canvas.getBoundingClientRect();
      origin = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const box = boxRef.current;
      if (box) {
        box.style.display = "block";
        box.style.left = `${origin.x}px`;
        box.style.top = `${origin.y}px`;
        box.style.width = "0px";
        box.style.height = "0px";
      }
    };

    const onMove = (event) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const box = boxRef.current;
      if (box) {
        box.style.left = `${Math.min(origin.x, x)}px`;
        box.style.top = `${Math.min(origin.y, y)}px`;
        box.style.width = `${Math.abs(x - origin.x)}px`;
        box.style.height = `${Math.abs(y - origin.y)}px`;
      }
    };

    const onUp = (event) => {
      if (!origin) return;
      const rect = canvas.getBoundingClientRect();
      const x1 = Math.min(origin.x, event.clientX - rect.left);
      const y1 = Math.min(origin.y, event.clientY - rect.top);
      const x2 = Math.max(origin.x, event.clientX - rect.left);
      const y2 = Math.max(origin.y, event.clientY - rect.top);
      origin = null;
      if (boxRef.current) boxRef.current.style.display = "none";
      map.setUserInteraction({ dragPanInteraction: true });
      if (x2 - x1 < 4 || y2 - y1 < 4) return;

      const features = renderedFeatures([
        [x1, y1],
        [x2, y2],
      ]);
      const ids = [
        ...new Set(features.filter((f) => f.id != null).map((f) => f.id)),
      ];
      applyClickActionToIds(ids);
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

  // ── Classification ────────────────────────────────────────────────────────
  // Recomputed whenever the thresholds or the user's edits change. The map is
  // repainted from the result in the effect below, so the slider recolours
  // without touching the server.
  useEffect(() => {
    const attrs = attrsRef.current;
    if (!attrs) return;
    const result = classifyAll(attrs, {
      threshold,
      unknownThreshold,
      overrides,
    });
    classesRef.current = result.classes;
    editedRef.current = result.edited;
    setClassification(result);
    setChangeCount(
      countClassChanges(
        attrs,
        baseline,
        { threshold, unknownThreshold },
        overrides
      )
    );
  }, [attrsVersion, threshold, unknownThreshold, overrides, baseline]);

  // Repaint on-screen footprints. isSourceReady is in the deps because the
  // layers are created inside the map's async "ready" handler — reading the
  // layer refs during render would see nulls and never re-run.
  useEffect(() => {
    if (!isSourceReady || !classification) return;
    hydrateViewport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classification, filter, isSourceReady]);

  // Resolve the map palette from the active Fluent theme, and re-apply it when
  // the user flips light/dark or changes the brand palette. The resolved
  // values live in a ref because only the renderer consumes them — the legend
  // uses the same tokens through makeStyles.
  useEffect(() => {
    const resolved = resolveThemeColors(rootRef.current);
    colorsRef.current = resolved;
    if (fillLayerRef.current) {
      fillLayerRef.current.setOptions({
        fillColor: fillColorExpression(resolved),
      });
    }
    if (lineLayerRef.current) {
      lineLayerRef.current.setOptions({
        strokeColor: strokeColorExpression(resolved),
      });
    }
  }, [isDark, palette, isSourceReady]);

  // ── Selection ─────────────────────────────────────────────────────────────
  const filteredIndices = useMemo(
    () => (classification ? filterIndices(classification, filter) : []),
    [classification, filter]
  );

  // Changing the filter can strand the current selection outside the visible
  // set, so snap it to the first match as part of the same event rather than
  // in an effect (which would cost an extra render pass).
  const handleFilterChange = useCallback(
    (nextFilter) => {
      setFilter(nextFilter);
      if (!classification) return;
      const nextIndices = filterIndices(classification, nextFilter);
      if (nextIndices.length === 0) return;
      setSelectedIndex((current) =>
        current >= 0 && !nextIndices.includes(current)
          ? nextIndices[0]
          : current
      );
    },
    [classification]
  );

  // Highlight the selected footprint, and pan to it when the selection came
  // from Prev/Next. Buildings whose tile has never rendered have no cached
  // centroid, so there is nowhere to pan yet.
  useEffect(() => {
    if (!isSourceReady) return;
    const attrs = attrsRef.current;
    const previousId = selectedIdRef.current;
    const nextId =
      attrs && selectedIndex >= 0 && selectedIndex < attrs.n
        ? attrs.ids[selectedIndex]
        : null;
    if (previousId != null && previousId !== nextId) {
      writeFeatureState(null, previousId, { selected: false });
    }
    selectedIdRef.current = nextId;
    if (nextId == null) return;
    writeFeatureState(null, nextId, { selected: true });
    const shouldPan = pendingPanRef.current;
    pendingPanRef.current = false;
    const centroid = centroidsRef.current.get(nextId);
    if (shouldPan && centroid && mapRef.current) {
      const camera = mapRef.current.getCamera();
      mapRef.current.setCamera({
        center: centroid,
        zoom: Math.max(camera?.zoom || 0, 17.5),
        duration: 500,
      });
    }
  }, [selectedIndex, isSourceReady]);

  function navigateInFilter(direction) {
    if (filteredIndices.length === 0) return;
    const attrs = attrsRef.current;
    // Prefer buildings we can actually pan to; fall back to the plain next
    // one so navigation never stalls.
    const hasLocation = (index) => {
      const id = attrs?.ids?.[index];
      return id != null && centroidsRef.current.has(id);
    };
    const next = nextIndexInList(
      filteredIndices,
      selectedIndex,
      direction,
      hasLocation
    );
    if (next === null) return;
    pendingPanRef.current = true;
    setSelectedIndex(next);
  }

  // ── Save ──────────────────────────────────────────────────────────────────
  async function refreshVersions() {
    try {
      const data = await apiGet(
        `GetEditedPredictionVersions?projectId=${encodeURIComponent(projectId)}` +
          `&modelId=${encodeURIComponent(modelId)}`
      );
      if (Array.isArray(data?.versions)) setVersions(data.versions);
    } catch (error) {
      console.warn("Could not refresh edited prediction versions:", error);
    }
  }

  async function handleSave() {
    setIsSaving(true);
    setSaveError("");
    try {
      const payload = buildSavePayload({
        projectId,
        imageLayerId,
        modelId,
        threshold,
        unknownThreshold,
        overrides,
      });
      const result = await apiPut("PutEditedPredictions", payload);
      // apiPut surfaces a conflict as the bare status code.
      if (result === 409) {
        throw new Error(
          "Another version is being written for this model. Try saving again in a moment."
        );
      }
      if (!result || result.version == null) {
        throw new Error("The server did not return a new version number.");
      }
      setSavedResult(result);
      // Subsequent slider moves are now measured against what was saved.
      setBaseline({ threshold, unknownThreshold });
      await refreshVersions();
      setDialog(
        "Saved",
        `Version ${result.version} saved with ${
          result.editedCount ?? payload.overrides.length
        } edited buildings.`
      );
    } catch (error) {
      const message =
        error?.message || "Failed to save the edited predictions.";
      setSaveError(message);
      setDialog("Save failed", message);
    } finally {
      setIsSaving(false);
    }
  }

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  // 1/2/3 set the selected building's class (and become the click action, so
  // the next click paints the same class); arrows walk the filtered set.
  useEffect(() => {
    if (phase !== PHASE_READY) return undefined;
    const classByKey = {
      1: CLASS_DAMAGED,
      2: CLASS_NOT_DAMAGED,
      3: CLASS_UNKNOWN,
    };
    function onKeyDown(event) {
      if (shouldIgnoreShortcut(event)) return;
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      const cls = classByKey[event.key];
      if (cls) {
        setClickAction(cls);
        setClassForSelected(cls);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        navigateInFilter(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        navigateInFilter(1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, selectedIndex, filteredIndices]);

  // ── Derived view data ─────────────────────────────────────────────────────
  const currentBuilding = useMemo(() => {
    const attrs = attrsRef.current;
    if (
      !attrs ||
      !classification ||
      selectedIndex < 0 ||
      selectedIndex >= attrs.n
    ) {
      return null;
    }
    const id = attrs.ids[selectedIndex];
    return {
      id,
      overtureId: attrs.overtureIds[selectedIndex],
      damage: attrs.damage[selectedIndex],
      unknown: attrs.unknown[selectedIndex],
      cls: classification.classes[selectedIndex],
      edited: classification.edited[selectedIndex],
    };
    // attrsVersion re-runs this once the sidecar lands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classification, selectedIndex, attrsVersion]);

  const legendItems = [
    { key: CLASS_DAMAGED, label: "Damaged", swatch: styles.legendDamaged },
    {
      key: CLASS_NOT_DAMAGED,
      label: "Not Damaged",
      swatch: styles.legendNotDamaged,
    },
    { key: CLASS_UNKNOWN, label: "Unknown", swatch: styles.legendUnknown },
  ];

  // ── Preparation card ──────────────────────────────────────────────────────
  // One card, three outcomes: waiting (live status + indeterminate progress),
  // terminally failed (error + forced retry), or gave up after the attempt
  // cap (check back later + a manual re-check).
  function renderPreparationCard() {
    const prep = prepState || {};
    const statusLabel = prepStatusLabel(prep.status);
    const outstanding = describeOutstandingArtifacts(session);
    const expected =
      Number(session?.buildingCount) > 0
        ? `${Number(session.buildingCount).toLocaleString()} buildings are expected.`
        : "";

    if (prep.phase === PREP_PHASE_FAILED) {
      return (
        <>
          <Text size={500}>Preparing predictions failed</Text>
          <MessageBar intent="error" className={styles.messageBar}>
            <MessageBarBody>
              <MessageBarTitle>{statusLabel}</MessageBarTitle>
              {prep.statusMessage ||
                prep.error ||
                "The job that builds the editable footprint tiles did not finish."}
            </MessageBarBody>
          </MessageBar>
          <div className={styles.messageDetail}>
            Retrying queues the preparation job again from scratch. Nothing
            already saved is affected.
          </div>
          <div className={styles.messageActions}>
            <Button appearance="primary" onClick={() => requestPreparation(true)}>
              Retry preparation
            </Button>
            <Button onClick={() => navigate(-1)}>Go back</Button>
          </div>
        </>
      );
    }

    if (prep.phase === PREP_PHASE_TIMED_OUT) {
      return (
        <>
          <Text size={500}>Still preparing predictions</Text>
          <div className={styles.messageBody}>
            This is taking longer than expected, so this page stopped checking.
            The job is still running in the background — check back later, or
            check now.
          </div>
          <div className={styles.prepStatusRow}>
            <span>Last known status</span>
            <span className={styles.prepStatusValue}>{statusLabel}</span>
          </div>
          {prep.statusMessage ? (
            <div className={styles.messageDetail}>{prep.statusMessage}</div>
          ) : null}
          {prep.error ? (
            <MessageBar intent="warning" className={styles.messageBar}>
              <MessageBarBody>{prep.error}</MessageBarBody>
            </MessageBar>
          ) : null}
          <div className={styles.messageActions}>
            <Button
              appearance="primary"
              onClick={() => requestPreparation(false)}
            >
              Check again
            </Button>
            <Button onClick={() => navigate(-1)}>Go back</Button>
          </div>
        </>
      );
    }

    // Requesting or waiting: the live view.
    const isRequesting = prep.phase === PREP_PHASE_REQUESTING;
    return (
      <>
        <Text size={500}>Preparing predictions for editing</Text>
        <ProgressBar
          className={styles.prepProgress}
          aria-label="Preparation progress"
        />
        {/* Live region scoped to the text that actually changes — announcing
            the whole card would re-read the buttons on every poll. */}
        <div className={styles.prepStatusRow} role="status" aria-live="polite">
          <span>Status</span>
          <span className={styles.prepStatusValue}>
            {isRequesting ? "Queuing" : statusLabel}
          </span>
        </div>
        {prep.statusMessage ? (
          <div className={styles.messageBody}>{prep.statusMessage}</div>
        ) : null}
        <div className={styles.messageBody}>
          {outstanding ||
            "The editable footprint tiles and prediction scores are being generated."}
        </div>
        {prep.error ? (
          <MessageBar intent="warning" className={styles.messageBar}>
            <MessageBarBody>
              {prep.error} Still retrying in the background.
            </MessageBarBody>
          </MessageBar>
        ) : null}
        <div className={styles.messageDetail}>
          This usually takes a few minutes. The map opens on its own when the
          data is ready — no need to reload.{expected ? ` ${expected}` : ""}
        </div>
        <div className={styles.messageDetail}>
          {prep.attempt > 0
            ? `Checked ${prep.attempt} ${
                prep.attempt === 1 ? "time" : "times"
              }, every ${Math.round(PREP_POLL_INTERVAL_MS / 1000)} seconds.`
            : "Waiting for the first status update."}
        </div>
      </>
    );
  }

  const showMap = phase === PHASE_LOADING || phase === PHASE_READY;

  return (
    <div className={styles.root} ref={rootRef}>
      <div className="labeling-tool-surface labeling-navigation-controls">
        <Button
          id="backButton"
          appearance="transparent"
          icon={<FluentIcon name="ChevronLeft" />}
          onClick={() => navigate(-1)}
        >
          Back
        </Button>
      </div>

      {showMap && (
        <div
          ref={mapContainerRef}
          id="predictionEditorMap"
          className={styles.map}
        />
      )}

      {phase === PHASE_LOADING && (
        <div className={styles.messageCard}>
          <Spinner label="Loading predictions…" />
          <div className={styles.messageDetail}>
            Streaming building footprints and prediction scores.
          </div>
        </div>
      )}

      {phase === PHASE_PREPARING && (
        <div className={styles.messageCard}>{renderPreparationCard()}</div>
      )}

      {phase === PHASE_EMPTY && (
        <div className={styles.messageCard}>
          <Text size={500}>No predicted buildings</Text>
          <div className={styles.messageBody}>
            This model has no building predictions to edit. Run inference (or,
            for an embedding model, predict all buildings in the Interactive
            Labeler) and then come back.
          </div>
        </div>
      )}

      {phase === PHASE_ERROR && (
        <div className={styles.messageCard}>
          <Text size={500}>Prediction editor unavailable</Text>
          <div className={styles.messageBody}>{errorMessage}</div>
          <div className={styles.messageActions}>
            {/* Only offered once a session has loaded: the model exists, so a
                missing or half-written artifact is worth rebuilding. When the
                session itself failed there is nothing to prepare. */}
            {session ? (
              <Button
                appearance="primary"
                onClick={() => requestPreparation(true)}
              >
                Rebuild artifacts
              </Button>
            ) : null}
            <Button
              appearance={session ? "secondary" : "primary"}
              onClick={() => navigate(-1)}
            >
              Go back
            </Button>
          </div>
        </div>
      )}

      {phase === PHASE_READY && classification && (
        <>
          <div className={styles.legend}>
            <div className={styles.legendTitle}>Current class</div>
            {legendItems.map((item) => (
              <div className={styles.legendRow} key={item.key}>
                <span className={`${styles.legendSwatch} ${item.swatch}`} />
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          <div className={styles.mapHint}>
            Click a footprint to change it &middot; Ctrl+drag to box-select
            &middot; right-click to undo an edit
          </div>
          <PredictionEditorRightPanel
            session={session}
            counts={classification.counts}
            total={classification.total}
            editedCount={classification.editedCount}
            filter={filter}
            setFilter={handleFilterChange}
            filteredIndices={filteredIndices}
            selectedIndex={selectedIndex}
            currentBuilding={currentBuilding}
            clickAction={clickAction}
            setClickAction={setClickAction}
            onSetClass={(cls) => {
              setClickAction(cls);
              setClassForSelected(cls);
            }}
            onClearOverride={clearSelectedOverride}
            onClearAllEdits={clearAllOverrides}
            onPrev={() => navigateInFilter(-1)}
            onNext={() => navigateInFilter(1)}
            threshold={threshold}
            setThreshold={setThreshold}
            unknownThreshold={unknownThreshold}
            setUnknownThreshold={setUnknownThreshold}
            baseline={baseline}
            changeCount={changeCount}
            onSave={handleSave}
            isSaving={isSaving}
            saveError={saveError}
            savedResult={savedResult}
            versions={versions}
          />
        </>
      )}

      {/* Box-select rectangle (Ctrl+drag) */}
      {showMap && <div ref={boxRef} className={styles.selectBox} />}
    </div>
  );
};

export default PredictionEditor;
