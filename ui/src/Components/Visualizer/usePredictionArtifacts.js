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
  shouldRequestPreparation,
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
      setIsLoading(true);
      setError("");
      // Streamed through the same-origin API proxy (managed identity server
      // side) so analysts behind the storage firewall can read them.
      const attrsUrl = buildUrl(artifactUrls.predictionAttrsUrl);
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
      // requests.
      const archiveUrl = buildUrl(artifactUrls.footprintTilesUrl);
      const protocol = getPmtilesProtocol();
      const buffer = await fetchArtifactBuffer(archiveUrl);
      if (isStale(runId)) return false;
      const archive = new PMTiles(
        new InMemoryPMTilesSource(archiveUrl, buffer)
      );
      if (protocol) protocol.add(archive);

      indexByIdRef.current = indexById(loadedAttrs);
      setBuildingCount(loadedAttrs.n);
      setAttrs(loadedAttrs);
      setArchiveKey(archiveUrl);
      setIsLoaded(true);
      setIsLoading(false);
      return true;
    },
    [artifactUrls, isStale]
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
  useEffect(() => {
    if (!resultsReady) return undefined;
    const runId = runRef.current + 1;
    runRef.current = runId;

    // Route params can change without remounting; start from a clean slate —
    // but keep whatever the results payload already told us, so a
    // vector-first API answers "how many buildings?" and "which versions
    // exist?" without a single extra request.
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
    // `results` is only read for its readiness flag and artifact URLs, both of
    // which are folded into artifactUrls / resultsReady.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, imageLayerId, modelId, resultsReady]);

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
        ready: prepState ? false : resolvePredictionsReady({ results, session }),
        buildingCount,
        // Only trusted while a job is not already running: once one is, the
        // poll knows more than the reason the page loaded with.
        reason: prepState ? "" : resolveReadinessReason(results),
      }),
    [isLoaded, isLoading, error, prepState, results, session, buildingCount]
  );

  return {
    status,
    isEmpty: status === FOOTPRINTS_EMPTY,
    error,
    readinessDetail: resolveReadinessDetail(results),
    activeVersion: resolveActiveVersion(results),
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
