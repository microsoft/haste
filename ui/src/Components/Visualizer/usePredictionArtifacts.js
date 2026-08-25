// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Loads the two artifacts the results page needs to draw predicted building
// footprints as vectors:
//
//   • the footprint PMTiles archive  (kind=footprint_pmtiles), and
//   • the per-building score sidecar (kind=prediction_attrs).
//
// Both are produced by a queued job — tippecanoe cannot run inside an HTTP
// handler — so a model nobody has opened before arrives here unprepared. This
// hook enqueues that job itself and then polls GetPredictionEditSession until
// the artifacts exist, rather than telling the user to come back later. The
// decisions behind that wait are pure and unit-tested (predictionPrep.js), as
// is the status the page renders from it (predictionResults.js).
//
// The hook deliberately does NOT touch the map: it hands back the archive key
// and the attribute arrays, and usePredictionFootprints turns those into
// layers on both panes of the swipe map.
//
// It also owns the edit *session* (flavor, threshold support, saved version
// history), fetched lazily: reading it costs the API a GeoPackage read, so a
// plain results view that finds its artifacts on the first try never asks for
// one. Entering edit mode does.
//
// VERSIONS. The sidecar is per version and the geometry is not: every saved
// version of a model describes the same buildings, so switching versions
// re-downloads the scores and reuses the PMTiles archive. The load is keyed
// on the resolved artifact URLs rather than on the route, which is what makes
// a version switch (a new results payload with a version-pinned
// `predictionAttrsUrl`) reload exactly as much as it has to — and a version
// whose sidecar has not been backfilled yet is reported as "preparing"
// instead of being drawn from the raw model's scores.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PMTiles } from "pmtiles";
import { apiGet, apiPut, buildUrl } from "../../util/api";
import {
  fetchArtifactBuffer,
  getPmtilesProtocol,
  InMemoryPMTilesSource,
} from "../../util/pmtiles.js";
import { indexById, normalizeAttrs } from "./predictionClassify.js";
import {
  FOOTPRINTS_EMPTY,
  resolveActiveVersion,
  resolveFootprintStatus,
  resolveInitialBuildingCount,
  resolveInitialVersions,
  resolvePredictionArtifacts,
  resolvePredictionsReady,
  resolveReadinessDetail,
  resolveReadinessReason,
  resolveVersionIsLatest,
  shouldRequestPreparation,
  versionSidecarPending,
} from "./predictionResults.js";
import {
  MAX_PREP_POLL_ATTEMPTS,
  PREP_PHASE_FAILED,
  PREP_PHASE_REQUESTING,
  PREP_POLL_INTERVAL_MS,
  applyPrepResponse,
  buildPrepRequest,
  evaluatePrepState,
  isPrepReady,
  nextPollAttempt,
  prepStateAfterPollError,
  shouldPollPrep,
} from "./predictionPrep.js";

const usePredictionArtifacts = ({
  projectId,
  imageLayerId,
  modelId,
  results,
  resultsReady,
}) => {
  // The id -> row index map is read inside long-lived map handlers, which
  // close over the render that registered them, so it lives in a ref. The
  // arrays themselves are handed out as a value: anything derived from them
  // during render (the selected building, the counts) must not read a ref.
  const indexByIdRef = useRef(new Map());
  // Guards every setState that happens after an await.
  const mountedRef = useRef(true);
  // Bumped whenever the route params change: async work captures the id it
  // started under and drops its result if a newer run has taken over.
  const runRef = useRef(0);
  // Latest session for the async prep helpers, which run outside the render
  // that produced `session`.
  const sessionRef = useRef(null);
  const sessionPromiseRef = useRef(null);
  // The PMTiles archive already downloaded and registered with the protocol.
  // Footprint geometry is shared by every version of a model, so a version
  // switch must not re-download it.
  const loadedArchiveRef = useRef("");
  // True once a backfill has been asked for on this run, so a version whose
  // sidecar is missing requests the job once rather than on every render.
  const backfillRequestedRef = useRef("");

  const [attrs, setAttrs] = useState(null);
  const [archiveKey, setArchiveKey] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState("");
  const [session, setSession] = useState(null);
  const [versions, setVersions] = useState([]);
  const [prepState, setPrepState] = useState(null);
  const [buildingCount, setBuildingCount] = useState(null);

  const artifactUrls = useMemo(
    () =>
      resolvePredictionArtifacts(results, {
        projectId,
        imageLayerId,
        modelId,
      }),
    [results, projectId, imageLayerId, modelId]
  );

  // The identity of what is being drawn: the sidecar decides every class on
  // the map, so this string changes exactly when a version switch (or a route
  // change) means the renderer has to be rebuilt. Held as a plain string so
  // effects can depend on it without re-running for an unrelated payload
  // refresh that happens to produce a new object.
  const attrsKey = artifactUrls.predictionAttrsUrl;
  const tilesKey = artifactUrls.footprintTilesUrl;
  // A version that was saved before its sidecar existed: nothing to fetch,
  // and the raw sidecar must never stand in for it.
  const versionPending = versionSidecarPending(results);

  const sessionEndpoint = useMemo(
    () =>
      `GetPredictionEditSession?projectId=${encodeURIComponent(projectId)}` +
      `&imageLayerId=${encodeURIComponent(imageLayerId)}` +
      `&modelId=${encodeURIComponent(modelId)}`,
    [projectId, imageLayerId, modelId]
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const isStale = useCallback(
    (runId) => !mountedRef.current || runId !== runRef.current,
    []
  );

  const adoptSession = useCallback((editSession) => {
    sessionRef.current = editSession;
    setSession(editSession);
    if (Array.isArray(editSession?.versions)) setVersions(editSession.versions);
    if (Number.isFinite(Number(editSession?.buildingCount))) {
      setBuildingCount(Number(editSession.buildingCount));
    }
  }, []);

  /**
   * The edit session, fetched at most once per route (and shared by every
   * caller that asks while the request is in flight).
   */
  const ensureSession = useCallback(
    async ({ refresh = false } = {}) => {
      if (!refresh && sessionRef.current) return sessionRef.current;
      if (!refresh && sessionPromiseRef.current) {
        return sessionPromiseRef.current;
      }
      const runId = runRef.current;
      const promise = apiGet(sessionEndpoint)
        .then((editSession) => {
          if (isStale(runId)) return editSession;
          adoptSession(editSession);
          return editSession;
        })
        .finally(() => {
          if (sessionPromiseRef.current === promise) {
            sessionPromiseRef.current = null;
          }
        });
      sessionPromiseRef.current = promise;
      return promise;
    },
    [sessionEndpoint, adoptSession, isStale]
  );

  const refreshVersions = useCallback(async () => {
    try {
      const data = await apiGet(
        `GetEditedPredictionVersions?projectId=${encodeURIComponent(
          projectId
        )}&modelId=${encodeURIComponent(modelId)}`
      );
      if (mountedRef.current && Array.isArray(data?.versions)) {
        setVersions(data.versions);
      }
    } catch (versionError) {
      console.warn(
        "Could not refresh edited prediction versions:",
        versionError
      );
    }
  }, [projectId, modelId]);

  // ── Artifact download ─────────────────────────────────────────────────────
  const loadArtifacts = useCallback(
    async (runId) => {
      if (!attrsKey || !tilesKey) {
        const failure = new Error(
          "This version's per-building predictions are not available yet."
        );
        failure.missing = true;
        throw failure;
      }
      setIsLoading(true);
      setError("");
      // Streamed through the same-origin API proxy (managed identity server
      // side) so analysts behind the storage firewall can read them. The URL
      // is version-pinned, so this is also the whole of a version switch.
      const attrsUrl = buildUrl(attrsKey);
      const response = await fetch(attrsUrl);
      if (!response.ok) {
        const notFound = response.status === 404;
        const failure = new Error(
          `Failed to load prediction attributes (HTTP ${response.status}).`
        );
        failure.missing = notFound;
        throw failure;
      }
      const loadedAttrs = normalizeAttrs(await response.json());
      if (isStale(runId)) return false;
      if (loadedAttrs.n === 0) {
        setBuildingCount(0);
        return false;
      }

      // Download the whole archive once and serve pmtiles.js from memory: the
      // SWA /api proxy in front of the function app does not honour range
      // requests. Every version of a model describes the SAME buildings, so
      // an archive already registered for this URL is reused rather than
      // re-downloaded on a version switch.
      const archiveUrl = buildUrl(tilesKey);
      const protocol = getPmtilesProtocol();
      if (loadedArchiveRef.current !== archiveUrl) {
        const buffer = await fetchArtifactBuffer(archiveUrl);
        if (isStale(runId)) return false;
        const archive = new PMTiles(
          new InMemoryPMTilesSource(archiveUrl, buffer)
        );
        if (protocol) protocol.add(archive);
        loadedArchiveRef.current = archiveUrl;
      }

      indexByIdRef.current = indexById(loadedAttrs);
      setBuildingCount(loadedAttrs.n);
      setAttrs(loadedAttrs);
      setArchiveKey(archiveUrl);
      setIsLoaded(true);
      setIsLoading(false);
      return true;
    },
    [attrsKey, tilesKey, isStale]
  );

  // ── Preparation ───────────────────────────────────────────────────────────
  // Nothing else in the app queues the job that builds these artifacts, so the
  // results page does it — once, without force, and again (with force) from
  // the Retry action after a terminal failure.
  const requestPreparation = useCallback(
    async (force = false) => {
      const runId = runRef.current;
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
        // job that had already finished starts the load immediately instead of
        // waiting out a poll interval.
        const merged = applyPrepResponse(sessionRef.current, response);
        adoptSession(merged);
        const decision = evaluatePrepState(merged, 0, MAX_PREP_POLL_ATTEMPTS);
        setPrepState(decision.ready ? null : decision);
      } catch (prepError) {
        if (isStale(runId)) return;
        console.error("Could not queue prediction tile preparation:", prepError);
        setPrepState({
          phase: PREP_PHASE_FAILED,
          status: "",
          statusMessage: "",
          attempt: 0,
          error:
            prepError?.message ||
            "The preparation job could not be queued. Try again.",
        });
      }
    },
    [projectId, imageLayerId, modelId, adoptSession, isStale]
  );

  // Artifacts are missing: find out why (an empty model never gets any) and,
  // unless there is nothing to build, get the job moving.
  const beginPreparation = useCallback(
    async (runId, reason = "") => {
      setIsLoading(false);
      // The server already ruled a job out — never processed, no predictions,
      // no buildings. Queueing one would poll forever against a job that can
      // never run, so show its explanation instead.
      if (!shouldRequestPreparation(reason)) return;
      let editSession = null;
      try {
        editSession = await ensureSession({ refresh: true });
      } catch (sessionError) {
        if (isStale(runId)) return;
        console.error("Could not read the prediction edit session:", sessionError);
        setError(
          "The predicted buildings could not be read for this model."
        );
        return;
      }
      if (isStale(runId)) return;
      if (Number(editSession?.buildingCount) === 0) {
        setBuildingCount(0);
        return;
      }
      if (isPrepReady(editSession)) {
        // The artifacts exist after all (a race with the job finishing);
        // try the download again rather than sitting on a preparing note.
        try {
          await loadArtifacts(runId);
        } catch (retryError) {
          if (isStale(runId)) return;
          setError(
            retryError?.message ||
              "The predicted building footprints could not be loaded."
          );
        }
        return;
      }
      await requestPreparation(false);
    },
    [ensureSession, isStale, loadArtifacts, requestPreparation]
  );

  // ── Load ──────────────────────────────────────────────────────────────────
  // Keyed on the resolved artifact URLs, not just the route: switching to
  // another saved version keeps the same model but points at that version's
  // own sidecar, and that is precisely when everything below has to be
  // thrown away and fetched again.
  useEffect(() => {
    if (!resultsReady) return undefined;
    const runId = runRef.current + 1;
    runRef.current = runId;

    // Route params (and the selected version) can change without remounting;
    // start from a clean slate — but keep whatever the results payload
    // already told us, so a vector-first API answers "how many buildings?"
    // and "which versions exist?" without a single extra request.
    setAttrs(null);
    indexByIdRef.current = new Map();
    sessionRef.current = null;
    sessionPromiseRef.current = null;
    setSession(null);
    setVersions(resolveInitialVersions(results));
    setPrepState(null);
    setArchiveKey("");
    setIsLoaded(false);
    setError("");
    const initialBuildingCount = resolveInitialBuildingCount(results);
    setBuildingCount(initialBuildingCount);

    const load = async () => {
      // Nothing was predicted: no job will ever produce footprints, so do not
      // ask for artifacts that cannot exist.
      if (initialBuildingCount === 0) return;
      const reason = resolveReadinessReason(results);
      // This version was saved before its sidecar was: there is genuinely
      // nothing to draw, and the raw model's scores must NOT stand in for it.
      // Ask for the backfill once (the prep job rebuilds missing versions)
      // and let the page sit on its "preparing" note until the poll upstairs
      // sees the sidecar appear.
      if (versionPending) {
        setIsLoading(false);
        if (backfillRequestedRef.current !== attrsKey) {
          backfillRequestedRef.current = attrsKey;
          await requestPreparation(false);
        }
        return;
      }
      // A payload that already says "not ready" saves us a doomed download.
      if (resolvePredictionsReady({ results }) === false) {
        await beginPreparation(runId, reason);
        return;
      }
      try {
        await loadArtifacts(runId);
      } catch (loadError) {
        if (isStale(runId)) return;
        setIsLoading(false);
        if (loadError?.missing) {
          // Not built yet (or not built for this model): the session says
          // which, and preparation takes it from there.
          await beginPreparation(runId, reason);
          return;
        }
        console.error("Could not load predicted building footprints:", loadError);
        setError(
          loadError?.message ||
            "The predicted building footprints could not be loaded."
        );
      }
    };

    load();

    return () => {
      // Nothing to dispose here: the map layers belong to
      // usePredictionFootprints, and the in-flight requests drop their
      // results through isStale().
      runRef.current += 1;
    };
    // `results` is only read for its readiness flags and artifact URLs, all of
    // which are folded into attrsKey / tilesKey / versionPending /
    // resultsReady. Listing `results` itself would reload the layer whenever
    // an unrelated field of the payload changed identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    projectId,
    imageLayerId,
    modelId,
    resultsReady,
    attrsKey,
    tilesKey,
    versionPending,
  ]);

  // ── Preparation polling ───────────────────────────────────────────────────
  // Each pass schedules exactly ONE timeout and then re-runs off the state it
  // wrote, so there is never more than one timer in flight. The cleanup clears
  // it, which is what stops polling on unmount and on a route change.
  useEffect(() => {
    if (!shouldPollPrep(prepState?.phase)) return undefined;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const runId = runRef.current;
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
          setPrepState(null);
          try {
            await loadArtifacts(runId);
          } catch (loadError) {
            if (cancelled || isStale(runId)) return;
            setError(
              loadError?.message ||
                "The predicted building footprints could not be loaded."
            );
          }
          return;
        }
        setPrepState(decision);
      } catch (pollError) {
        if (cancelled || isStale(runId)) return;
        // A blip in the API must not abandon a healthy job: keep the last
        // known status and count the attempt against the cap.
        setPrepState((previous) =>
          prepStateAfterPollError(
            previous,
            pollError?.message,
            MAX_PREP_POLL_ATTEMPTS
          )
        );
      }
    }, PREP_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [prepState, sessionEndpoint, adoptSession, isStale, loadArtifacts]);

  const status = useMemo(
    () =>
      resolveFootprintStatus({
        loaded: isLoaded,
        loading: isLoading,
        error,
        // A version with no sidecar is never "ready", whatever the
        // model-level flags say: those describe the raw artifacts, which this
        // version may not use.
        ready:
          prepState || versionPending
            ? false
            : resolvePredictionsReady({ results, session }),
        buildingCount,
        // Only trusted while a job is not already running: once one is, the
        // poll knows more than the reason the page loaded with. A pending
        // version keeps its own reason, because the job that fixes it is the
        // backfill rather than anything the poll watches.
        reason:
          prepState && !versionPending ? "" : resolveReadinessReason(results),
      }),
    [
      isLoaded,
      isLoading,
      error,
      prepState,
      versionPending,
      results,
      session,
      buildingCount,
    ]
  );

  return {
    status,
    isEmpty: status === FOOTPRINTS_EMPTY,
    error,
    readinessDetail: resolveReadinessDetail(results),
    activeVersion: resolveActiveVersion(results),
    // Whether the served version is the newest saved state (server-decided),
    // and whether it is one whose sidecar is still being backfilled.
    versionIsLatest: resolveVersionIsLatest(results),
    versionPending,
    versionsPending: session?.versionsPending ?? null,
    // Changes exactly when the thing being drawn changes, so the renderer can
    // rebuild both swipe panes from scratch on a version switch.
    renderKey: attrsKey,
    attrs,
    indexByIdRef,
    archiveKey,
    session,
    ensureSession,
    versions,
    refreshVersions,
    prepState,
    requestPreparation,
  };
};

export default usePredictionArtifacts;
