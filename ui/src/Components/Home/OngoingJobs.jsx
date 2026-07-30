// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Spinner } from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../../util/api";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import NoResultsMessage from "../NoResultsMessage";

// A job is "ongoing" when its status is set and not in a terminal state.
const TERMINAL_STATES = new Set([
  "Processed",
  "Completed",
  "Failed",
  "Cancelled",
]);

const isOngoing = (status) =>
  typeof status === "string" &&
  status.length > 0 &&
  !TERMINAL_STATES.has(status);

/** Collect ongoing imagery/training/inference jobs from a project detail. */
function extractJobs(projectId, project) {
  const jobs = [];
  const projectName = project.name || "Project";

  (project.imageLayer || []).forEach((layer) => {
    const target = `/project/${projectId}/${layer.imageLayerId}`;

    if (isOngoing(layer.status)) {
      jobs.push({
        key: `layer-${layer.imageLayerId}`,
        kind: "Imagery",
        projectName,
        name: layer.name,
        target,
        indicator: {
          id: `ongoingImagery-${layer.imageLayerId}`,
          currentStep: layer.currentStep,
          totalSteps: layer.totalSteps,
          progressPct: layer.progressPct,
          status: layer.status,
          statusMessage: layer.statusMessage || "",
          prefix: "Imagery",
          contextLabel: `Image Layer: ${layer.name}`,
        },
      });
    }

    (layer.models || []).forEach((model) => {
      const isInference = !!model.inferenceStatus;

      if (isInference && isOngoing(model.inferenceStatus)) {
        jobs.push({
          key: `inference-${model.modelId}`,
          kind: "Inference",
          projectName,
          name: model.name,
          target,
          indicator: {
            id: `ongoingInference-${model.modelId}`,
            currentStep: model.inferenceCurrentStep,
            totalSteps: model.inferenceTotalSteps,
            progressPct: model.inferenceProgressPct,
            status: model.inferenceStatus,
            statusMessage: model.inferenceStatusMessage || "",
            prefix: "Inference",
            contextLabel: `Model: ${model.name} \u00b7 Inference`,
          },
        });
      } else if (!isInference && isOngoing(model.status)) {
        jobs.push({
          key: `training-${model.modelId}`,
          kind: "Training",
          projectName,
          name: model.name,
          target,
          indicator: {
            id: `ongoingTraining-${model.modelId}`,
            currentStep: model.currentStep,
            totalSteps: model.totalSteps,
            progressPct: model.progressPct,
            status: model.status,
            statusMessage: model.statusMessage || "",
            prefix: "Training",
            contextLabel: `Model: ${model.name} \u00b7 Training`,
          },
        });
      }
    });
  });

  return jobs;
}

// Load project details for the projects that could have running work and
// surface every in-progress imagery/training/inference job. This runs after
// the dashboard summary is already on screen, with its own in-block spinner,
// because walking each project's models can take a while.
const OngoingJobs = ({ projects }) => {
  OngoingJobs.propTypes = {
    projects: PropTypes.array.isRequired,
  };

  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [jobs, setJobs] = useState([]);

  const projectKey = projects.map((p) => p.projectId).join("|");

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);

      const candidates = projects.filter(
        (p) => (p.imageLayerCount || 0) > 0 || (p.modelsCount || 0) > 0
      );

      const results = await Promise.all(
        candidates.map((p) =>
          apiGet(
            `GetProjectDetails?projectId=${p.projectId}&includeModels=True`
          )
            .then((res) => ({ projectId: p.projectId, res }))
            .catch(() => null)
        )
      );

      if (cancelled) return;

      const collected = [];
      results.forEach((item) => {
        if (item && item.res) {
          collected.push(...extractJobs(item.projectId, item.res));
        }
      });

      setJobs(collected);
      setLoading(false);
    };

    load();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey]);

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
        <NoResultsMessage
          title="No ongoing jobs"
          fallbackMessage="Everything is up to date."
        />
      </div>
    );
  }

  return (
    <div className="dash-jobs-list">
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
