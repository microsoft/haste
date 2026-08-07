// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import {
  Button,
  MessageBar,
  MessageBarBody,
  Spinner,
} from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../../util/api";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import NoResultsMessage from "../NoResultsMessage";
import { extractJobs } from "./ongoingJobsUtils";

const REFRESH_INTERVAL_MS = 30000;

// Load project details for the projects that could have running work and
// surface every in-progress imagery/training/inference job. This runs after
// the dashboard summary is already on screen, with its own in-block spinner,
// because walking each project's models can take a while.
const OngoingJobs = ({ projects }) => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [jobs, setJobs] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);

  const projectKey = projects
    .filter((project) =>
      (project.imageLayerCount || 0) > 0 || (project.modelsCount || 0) > 0
    )
    .map((project) => project.projectId)
    .join("|");

  useEffect(() => {
    let cancelled = false;
    const projectIds = projectKey ? projectKey.split("|") : [];

    const load = async (initialLoad = false) => {
      if (initialLoad) setLoading(true);

      const results = await Promise.allSettled(
        projectIds.map((projectId) =>
          apiGet(
            `GetProjectDetails?projectId=${projectId}&includeModels=True`
          )
            .then((res) => ({ projectId, res }))
        )
      );

      if (cancelled) return;

      const collected = [];
      let failedCount = 0;
      results.forEach((result) => {
        if (result.status === "fulfilled") {
          collected.push(
            ...extractJobs(result.value.projectId, result.value.res)
          );
        } else {
          failedCount += 1;
        }
      });

      setJobs(collected);
      setLoadError(
        failedCount > 0
          ? `${failedCount} of ${projectIds.length} projects could not be refreshed.`
          : ""
      );
      setLoading(false);
    };

    load(true);
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [projectKey, refreshToken]);

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

OngoingJobs.propTypes = {
  projects: PropTypes.array.isRequired,
};

export default OngoingJobs;
