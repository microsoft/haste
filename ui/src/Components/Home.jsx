// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Button,
  MessageBar,
  MessageBarBody,
  Text,
  Tooltip,
} from "@fluentui/react-components";
import OpenProject from "./Home/OpenProject";
import OngoingJobs from "./Home/OngoingJobs";
import { useState, useEffect, useContext } from "react";

import { AppContext } from "../AppContext";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../util/api";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import { FluentIcon } from "../util/icons";
import PropTypes from "prop-types";
import { formatProjectDate } from "./ProjectManagement/projectStatus";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { loadHomeData } from "./Home/loadHomeData";
import { RouteLoading } from "./MapRoute";

const StatCard = ({ icon, value, label, onClick }) => (
  <div
    className={`dash-kpi${onClick ? " dash-kpi--clickable" : ""}`}
    role={onClick ? "button" : undefined}
    tabIndex={onClick ? 0 : undefined}
    onClick={onClick}
    onKeyDown={(e) => {
      if (onClick && (e.key === "Enter" || e.key === " ")) onClick();
    }}
  >
    <span className="dash-kpi-icon">
      <FluentIcon name={icon} />
    </span>
    <span className="dash-kpi-body">
      <span className="dash-kpi-value">{value}</span>
      <span className="dash-kpi-label">{label}</span>
    </span>
    {onClick && (
      <FluentIcon
        name="chevronright"
        className="dash-kpi-go"
        aria-hidden="true"
      />
    )}
  </div>
);

StatCard.propTypes = {
  icon: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
  label: PropTypes.string.isRequired,
  onClick: PropTypes.func,
};

const WidgetShell = ({ title, subtitle, icon, action, className, children }) => (
  <section className={`home-box dash-widget p-4 h-100${className ? ` ${className}` : ""}`}>
    <div className="dash-widget-header mb-3">
      <div className="dash-widget-header-main">
        <h5 className="home-title mb-1 d-flex align-items-center gap-2">
          {icon ? <FluentIcon name={icon} /> : null}
          {title}
        </h5>
        {subtitle ? <p className="dash-widget-subtitle mb-0">{subtitle}</p> : null}
      </div>
      {action ? <div className="dash-widget-action">{action}</div> : null}
    </div>
    {children}
  </section>
);

WidgetShell.propTypes = {
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  icon: PropTypes.string,
  action: PropTypes.node,
  className: PropTypes.string,
  children: PropTypes.node.isRequired,
};

const EmptyWidgetPlaceholder = ({ message }) => (
  <div className="dash-empty-placeholder" role="status">
    <FluentIcon name="info" aria-hidden="true" />
    <Text>{message}</Text>
  </div>
);

EmptyWidgetPlaceholder.propTypes = {
  message: PropTypes.string.isRequired,
};

const Home = () => {
  const navigate = useNavigate();
  const { initCurrentTour, setAppHeaderRightButtons, appParams } =
    useContext(AppContext);
  const [dashboardData, setDashboardData] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [modalComponent, setModalComponent] = useState(null);
  const [nowMs] = useState(Date.now);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  const openCreateProjectModal = () => {
    setModalComponent(
      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
    );
  };

  useEffect(() => {
    let active = true;
    initCurrentTour("dashboardGuide");
    setAppHeaderRightButtons([
      {
        iconName: "help",
        title: "Help",
        id: "helpButton",
        onClick: () => {
          setGuidedTourState(
            false,
            initCurrentTour,
            "dashboardGuide",
            appParams.guidedTourProperties
          );
        },
      },
    ]);

    const controller = new AbortController();
    const { dashboard, catalog: catalogRequest } = loadHomeData(apiGet, {
      signal: controller.signal,
    });
    dashboard
      .then((response) => {
        if (!active) return;
        setDashboardData(response);
        setLoadError(false);
      })
      .catch((error) => {
        if (!active || error.name === "AbortError") return;
        console.error("Error fetching projects:", error);
        setLoadError(true);
      });
    catalogRequest
      .then((response) => {
        if (active) setCatalog(response);
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") {
          console.warn("Model catalog unavailable for dashboard:", error);
        }
      });

    //On component dismount
    return () => {
      active = false;
      controller.abort();
      setModalComponent(null);
      initGuidedTourState("dashboardGuide", appParams.guidedTourProperties);
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadAttempt]);

  if (!dashboardData) {
    return loadError ? (
      <div className="p-4 w-100">
        <MessageBar intent="error">
          <MessageBarBody>
            Dashboard data could not be loaded.
          </MessageBarBody>
        </MessageBar>
        <Button
          className="mt-3"
          appearance="primary"
          onClick={() => {
            setLoadError(false);
            setLoadAttempt((value) => value + 1);
          }}
        >
          Retry
        </Button>
      </div>
    ) : <RouteLoading label="Loading dashboard" />;
  }

  const projects = dashboardData.projects || [];
  const isEmpty = projects.length === 0;
  const isAdmin = appParams.userRoles?.includes("administrators");
  const isMobileLayout = Number(appParams.bootstrapBreakpoint) <= 2;

  const totals = projects.reduce(
    (acc, project) => {
      acc.layers += project.imageLayerCount || 0;
      acc.models += project.modelsCount || 0;
      acc.labels += project.labelsCount || 0;
      return acc;
    },
    { layers: 0, models: 0, labels: 0 }
  );

  const countries = [
    ...new Set(projects.flatMap((project) => project.affectedCountries || [])),
  ]
    .filter(Boolean)
    .sort();

  const newLast30 = projects.filter((project) => {
    const created = Date.parse(project.creationDate);
    return !Number.isNaN(created) && nowMs - created <= 30 * 86400000;
  }).length;

  const projectsByCountry = projects.reduce((acc, project) => {
    (project.affectedCountries || []).forEach((country) => {
      if (country) {
        acc[country] = (acc[country] || 0) + 1;
      }
    });
    return acc;
  }, {});

  const topCountries = Object.entries(projectsByCountry)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8);

  const projectsWithModels = projects.filter(
    (project) => (project.modelsCount || 0) > 0
  ).length;
  const modelCoverage =
    projects.length > 0
      ? Math.round((projectsWithModels / projects.length) * 100)
      : 0;

  const avgLayers =
    projects.length > 0 ? (totals.layers / projects.length).toFixed(1) : "0.0";
  const avgLabels =
    projects.length > 0 ? (totals.labels / projects.length).toFixed(1) : "0.0";

  const attentionProjects = projects
    .filter((project) => (project.imageLayerCount || 0) === 0)
    .sort((a, b) => Date.parse(a.creationDate) - Date.parse(b.creationDate))
    .slice(0, 4);

  return (
    <>
        <div className={`home-dashboard-page${isEmpty ? " home-dashboard-page--empty" : ""}`}>
          <div className="home-dashboard-content d-flex col-12 container flex-column align-items-center">
            <div className="row w-100 mb-3">
            <div className="d-flex col-12 align-items-start flex-wrap gap-3">
              <div className="w-100">
                {!isMobileLayout && <h3 className="home-title mb-1">HASTE</h3>}
                <Text className="dash-dashboard-subtitle d-block">
                  <span className="fw-semibold">
                    <b>H</b>igh-speed <b>A</b>ssessment and <b>S</b>atellite{" "}
                    <b>T</b>racking for <b>E</b>mergencies{" "}
                  </span>
                  is an AI-powered tool designed by the{" "}
                  <span className="fw-semibold">Microsoft AI for Good Lab </span>
                  to quickly identify and evaluate structural damage to buildings
                  after a catastrophe.
                </Text>
              </div>
            </div>
          </div>

            <div className="row w-100 mb-3">
              <div className="col-12">
                <div className="dash-kpis">
                  <button
                    type="button"
                    id={"dashboardStartProject"}
                    className="dash-kpi dash-kpi-create dash-kpi-create-button"
                    onClick={openCreateProjectModal}
                  >
                    <span className="dash-kpi-create-text">Start a Project</span>
                  </button>
                  <StatCard
                    icon="folderhorizontal"
                    value={projects.length}
                    label="Projects"
                    onClick={!isEmpty ? () => navigate("/projects") : undefined}
                  />
                  <StatCard
                    icon="reportdocument"
                    value={catalog.length}
                    label="Catalog Models"
                    onClick={!isEmpty && isAdmin ? () => navigate("/model-catalog") : undefined}
                  />
                  <StatCard icon="fileimage" value={totals.layers} label="Image Layers" />
                  <StatCard icon="modelingview" value={totals.models} label="Models" />
                  <StatCard icon="bulletedlist" value={totals.labels} label="Labels" />
                  <StatCard icon="globe" value={countries.length} label="Countries" />
                </div>
              </div>
            </div>

            <div className="row w-100 g-3 dash-main-grid">
              <div className="col-12 col-xxl-8">
                <WidgetShell
                  title="Recent Projects"
                  subtitle="Newest projects with quick context and key counts"
                  icon="folderhorizontal"
                  action={
                    <Button
                      appearance="subtle"
                      disabled={isEmpty}
                      onClick={() => navigate("/projects")}
                    >
                      View all
                    </Button>
                  }
                >
                  {isEmpty ? (
                    <EmptyWidgetPlaceholder message="No recent projects to display." />
                  ) : (
                    <div className="dash-recent-list">
                      {projects.slice(0, 3).map((project, index) => (
                        <OpenProject
                          key={project.projectId}
                          openProject={project}
                          index={index}
                        />
                      ))}
                    </div>
                  )}
                </WidgetShell>
              </div>

            <div className="col-12 col-xxl-4">
              <WidgetShell
                title="Ongoing Jobs"
                subtitle="Imagery processing, training and inference currently running"
                icon="releasedefinition"
                className="dash-widget--jobs"
              >
                {isEmpty ? (
                  <EmptyWidgetPlaceholder message="No ongoing jobs to display." />
                ) : (
                  <OngoingJobs />
                )}
              </WidgetShell>
            </div>

            <div className="col-12 col-xl-6 col-xxl-4">
              <WidgetShell
                title="Activity Snapshot"
                subtitle="Rolling health indicators for daily operations"
                icon="calendar"
              >
                {isEmpty ? (
                  <EmptyWidgetPlaceholder message="No activity data available." />
                ) : (
                  <><div className="dash-snapshot-grid">
                  <div className="dash-snapshot-item">
                    <div className="dash-snapshot-value">{newLast30}</div>
                    <div className="dash-snapshot-label">New projects (30d)</div>
                  </div>
                  <div className="dash-snapshot-item">
                    <div className="dash-snapshot-value">{avgLayers}</div>
                    <div className="dash-snapshot-label">Avg layers / project</div>
                  </div>
                  <div className="dash-snapshot-item">
                    <div className="dash-snapshot-value">{avgLabels}</div>
                    <div className="dash-snapshot-label">Avg labels / project</div>
                  </div>
                  <div className="dash-snapshot-item">
                    <div className="dash-snapshot-value">{modelCoverage}%</div>
                    <div className="dash-snapshot-label">Model coverage</div>
                  </div>
                  </div>
                  {newLast30 > 0 && (
                  <span className="dash-new-badge d-inline-block mt-3">
                    {newLast30} new in the last 30 days
                  </span>
                  )}</>
                )}
              </WidgetShell>
            </div>

            <div className="col-12 col-xl-6 col-xxl-4">
              <WidgetShell
                title="Geographic Coverage"
                subtitle="Most represented countries across active projects"
                icon="globe"
                className="dash-widget--dark"
              >
                {!isEmpty && topCountries.length > 0 ? (
                  <div className="dash-bars">
                    {topCountries.map(([country, count]) => {
                      const max = topCountries[0][1] || 1;
                      return (
                        <div className="dash-bar-row" key={country}>
                          <Tooltip content={country} relationship="label">
                            <span className="dash-bar-label">{country}</span>
                          </Tooltip>
                          <span className="dash-bar-track">
                            <span
                              className="dash-bar-fill"
                              style={{ width: `${Math.round((count / max) * 100)}%` }}
                            />
                          </span>
                          <span className="dash-bar-value">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <EmptyWidgetPlaceholder message="No geographic data available." />
                )}
              </WidgetShell>
            </div>

            <div className="col-12 col-xxl-4">
              <WidgetShell
                title="Needs Attention"
                subtitle="Oldest projects that still have no imagery layers"
                icon="info"
              >
                {!isEmpty && attentionProjects.length > 0 ? (
                  <div className="dash-attention-list">
                    {attentionProjects.map((project) => (
                      <button
                        type="button"
                        key={project.projectId}
                        className="dash-attention-item"
                        onClick={() => navigate(`/project/${project.projectId}`)}
                      >
                        <span className="dash-attention-name">{project.name}</span>
                        <span className="dash-attention-meta">
                          Created {formatProjectDate(project.creationDate)}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <EmptyWidgetPlaceholder message="No projects to review yet." />
                )}
              </WidgetShell>
            </div>
            </div>
          </div>
        </div>

      {modalComponent}
    </>
  );
};

export default Home;
