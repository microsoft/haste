// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState } from "react";
import {
  Button,
  MessageBar,
  MessageBarBody,
  Spinner,
} from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";
import { apiGetResponse } from "../../util/api";
import { createSingleFlight } from "../../util/singleFlight";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import NoResultsMessage from "../NoResultsMessage";
import {
  ACTIVE_JOBS_ENDPOINT,
  activeJobsAfterResponse,
  activeJobsHeaders,
  shouldPollActiveJobs,
} from "./activeJobsRequest";

const REFRESH_INTERVAL_MS = 30000;

const OngoingJobs = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [jobs, setJobs] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);
  const requestRef = useRef(createSingleFlight());
  const etagRef = useRef(null);

  useEffect(() => {
    let mounted = true;
    const request = requestRef.current;

    const load = async (initialLoad = false) => {
      if (request.isRunning(ACTIVE_JOBS_ENDPOINT)) return;
      if (initialLoad) setLoading(true);
      try {
        await request.run(ACTIVE_JOBS_ENDPOINT, async (signal) => {
          const { data, etag, status } = await apiGetResponse(
            ACTIVE_JOBS_ENDPOINT,
            {
              signal,
              headers: activeJobsHeaders(etagRef.current),
            }
          );
          if (!mounted) return;
          if (etag) etagRef.current = etag;
          setJobs((current) =>
            activeJobsAfterResponse(current, { data, status })
          );
          setLoadError("");
        });
      } catch (error) {
        if (error.name !== "AbortError" && mounted) {
          setLoadError("Ongoing jobs could not be refreshed.");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load(true);
    const intervalId = window.setInterval(() => {
      if (
        shouldPollActiveJobs({
          visibilityState: document.visibilityState,
          requestRunning: request.isRunning(ACTIVE_JOBS_ENDPOINT),
        })
      ) {
        load();
      }
    }, REFRESH_INTERVAL_MS);

    return () => {
      mounted = false;
      window.clearInterval(intervalId);
      request.abort();
    };
  }, [refreshToken]);

  if (loading) {
    return (
      <div className="dash-jobs-loading">
        <Spinner size="small" label="Checking for ongoing jobs…" />
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="dash-jobs-empty">
        {loadError ? (
          <MessageBar intent="error">
            <MessageBarBody>{loadError}</MessageBarBody>
            <Button size="small" onClick={() => setRefreshToken((value) => value + 1)}>
              Retry
            </Button>
          </MessageBar>
        ) : (
          <NoResultsMessage
            title="No ongoing jobs"
            fallbackMessage="Everything is up to date."
          />
        )}
      </div>
    );
  }

  return (
    <div className="dash-jobs-list" aria-live="polite">
      {loadError && (
        <MessageBar intent="warning">
          <MessageBarBody>{loadError}</MessageBarBody>
          <Button size="small" onClick={() => setRefreshToken((value) => value + 1)}>
            Retry
          </Button>
        </MessageBar>
      )}
      {jobs.map((job) => (
        <div className="dash-job-row" key={job.key}>
          <button
            type="button"
            className="dash-job-link"
            onClick={() => navigate(job.target)}
            title={`${job.projectName} · ${job.name}`}
          >
            <span className={`dash-job-kind dash-job-kind--${job.kind.toLowerCase()}`}>
              {job.kind}
            </span>
            <span className="dash-job-name">{job.name}</span>
            <span className="dash-job-project">{job.projectName}</span>
          </button>
          <div className="dash-job-status">
            <StatusIndicator {...job.indicator} />
          </div>
        </div>
      ))}
    </div>
  );
};

export default OngoingJobs;
