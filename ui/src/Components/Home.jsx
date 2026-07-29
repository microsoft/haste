// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { Button, Text, Tooltip } from "@fluentui/react-components";
import OpenProject from "./Home/OpenProject";
import { useState, useEffect, useContext } from "react";
import { Doughnut, Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  ArcElement,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip as ChartTooltip,
  Legend,
} from "chart.js";

import { AppContext } from "../AppContext";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../util/api";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";
import { FluentIcon } from "../util/icons";
import PropTypes from "prop-types";
import { formatProjectDate } from "./ProjectManagement/projectStatus";
import CreateEditProjectModal from "./CreateEditProjectModal";
import { useTheme } from "../util/ThemeContext";
import { getPalette } from "../util/theme";

import StartProjectButton from "./StartProjectButton";

/** Convert a #rrggbb hex to an rgba() string with the given alpha. */
function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.substring(0, 2), 16);
  const g = parseInt(value.substring(2, 4), 16);
  const b = parseInt(value.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

ChartJS.register(
  ArcElement,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ChartTooltip,
  Legend
);

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


const Home = () => {
  const navigate = useNavigate();
  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams, setAppParams } =
    useContext(AppContext);
  const { palette } = useTheme();
  const dashPalette = {
    primary: getPalette(palette).ramp[80],
    accent: getPalette(palette).ramp[100],
    neutral: "#8F8F8F",
  };
  const [dashboardData, setDashboardData] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [modalComponent, setModalComponent] = useState(null);

  const openCreateProjectModal = () => {
    setModalComponent(
      <CreateEditProjectModal onClose={() => setModalComponent(null)} />
    );
  };

  useEffect(() => {
    const fetchProjects = async () => {
      setIsLoading(true);
      try {
        const response = await apiGet("GetDashboardData");
        setDashboardData(response);
      } catch (error) {
        console.error("Error fetching projects:", error);
      }
      try {
        const catalogResponse = await apiGet("GetModelCatalog");
        setCatalog(catalogResponse?.modelCatalog || []);
      } catch (error) {
        // Catalog is supplementary; ignore if unavailable.
        console.warn("Model catalog unavailable for dashboard:", error);
      }
      setIsLoading(false);
    };

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

    fetchProjects();

    //On component dismount
    return () => {
      setModalComponent(null);
      initGuidedTourState("dashboardGuide", appParams.guidedTourProperties);
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!dashboardData) {
    return <> </>;
  }

  const projects = dashboardData.projects || [];
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

  const nowMs = Date.now();
  const newLast30 = projects.filter((project) => {
    const created = Date.parse(project.creationDate);
    return !Number.isNaN(created) && nowMs - created <= 30 * 86400000;
  }).length;

  const operationsMixData = {
    labels: ["Image Layers", "Models", "Labels"],
    datasets: [
      {
        data: [totals.layers, totals.models, totals.labels],
        backgroundColor: [
          dashPalette.primary,
          dashPalette.accent,
          dashPalette.neutral,
        ],
        borderWidth: 0,
      },
    ],
  };

  const totalOperations = totals.layers + totals.models + totals.labels;

  const monthLabels = [];
  const monthKeys = [];
  const monthCountMap = {};
  const monthCursor = new Date(nowMs);
  monthCursor.setDate(1);
  for (let i = 5; i >= 0; i -= 1) {
    const d = new Date(monthCursor.getFullYear(), monthCursor.getMonth() - i, 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleString("en-US", { month: "short" });
    monthKeys.push(key);
    monthLabels.push(label);
    monthCountMap[key] = 0;
  }

  projects.forEach((project) => {
    const created = new Date(project.creationDate);
    if (!Number.isNaN(created.getTime())) {
      const key = `${created.getFullYear()}-${String(created.getMonth() + 1).padStart(2, "0")}`;
      if (Object.prototype.hasOwnProperty.call(monthCountMap, key)) {
        monthCountMap[key] += 1;
      }
    }
  });

  const monthlyCreationData = {
    labels: monthLabels,
    datasets: [
      {
        label: "Projects created",
        data: monthKeys.map((key) => monthCountMap[key]),
        fill: true,
        borderColor: dashPalette.primary,
        backgroundColor: hexToRgba(dashPalette.primary, 0.16),
        pointRadius: 4,
        pointBackgroundColor: dashPalette.primary,
        tension: 0.28,
      },
    ],
  };

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
      {projects.length > 0 ? (
        <div className="home-dashboard-page">
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
                    onClick={() => navigate("/projects")}
                  />
                  <StatCard icon="fileimage" value={totals.layers} label="Image Layers" />
                  <StatCard icon="modelingview" value={totals.models} label="Models" />
                  <StatCard icon="bulletedlist" value={totals.labels} label="Labels" />
                  <StatCard
                    icon="reportdocument"
                    value={catalog.length}
                    label="Catalog Models"
                    onClick={isAdmin ? () => navigate("/model-catalog") : undefined}
                  />
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
                    <Button appearance="subtle" onClick={() => navigate("/projects")}>
                      View all
                    </Button>
                  }
                >
                  <div className="dash-recent-list">
                    {projects.slice(0, 3).map((project, index) => (
                      <OpenProject
                        key={project.projectId}
                        openProject={project}
                        index={index}
                      />
                    ))}
                  </div>
                </WidgetShell>
              </div>

            <div className="col-12 col-xxl-4">
              <WidgetShell
                title="Operational Signals"
                subtitle="Live indices based on data volume and project creation velocity"
                icon="analyticsreport"
              >
                <div className="dash-chart-grid">
                  <div className="dash-chart-wrap">
                    <Doughnut
                      data={operationsMixData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: {
                            display: false,
                          },
                        },
                        cutout: "68%",
                      }}
                    />
                    <div className="dash-status-chart-center">
                      <div className="dash-status-total">{totalOperations}</div>
                      <div className="dash-status-total-label">assets</div>
                    </div>
                  </div>
                  <div className="dash-status-legend">
                    <div className="dash-status-row">
                      <span className="dash-status-dot dash-status-dot--active" />
                      <span className="dash-status-label">Image Layers</span>
                      <span className="dash-status-count">{totals.layers}</span>
                    </div>
                    <div className="dash-status-row">
                      <span className="dash-status-dot dash-status-dot--modeled" />
                      <span className="dash-status-label">Models</span>
                      <span className="dash-status-count">{totals.models}</span>
                    </div>
                    <div className="dash-status-row">
                      <span className="dash-status-dot dash-status-dot--labels" />
                      <span className="dash-status-label">Labels</span>
                      <span className="dash-status-count">{totals.labels}</span>
                    </div>
                  </div>
                </div>
                <div className="dash-trend-wrap mt-3">
                  <div className="dash-trend-title">Projects created in last 6 months</div>
                  <div className="dash-trend-chart">
                    <Line
                      data={monthlyCreationData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: {
                            display: false,
                          },
                        },
                        scales: {
                          x: {
                            grid: {
                              display: false,
                            },
                          },
                          y: {
                            beginAtZero: true,
                            ticks: {
                              precision: 0,
                            },
                          },
                        },
                      }}
                    />
                  </div>
                </div>
              </WidgetShell>
            </div>

            <div className="col-12 col-xl-6 col-xxl-4">
              <WidgetShell
                title="Activity Snapshot"
                subtitle="Rolling health indicators for daily operations"
                icon="calendar"
              >
                <div className="dash-snapshot-grid">
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
                {topCountries.length > 0 ? (
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
                  <Text>No affected countries registered yet.</Text>
                )}
              </WidgetShell>
            </div>

            <div className="col-12 col-xxl-4">
              <WidgetShell
                title="Needs Attention"
                subtitle="Oldest projects that still have no imagery layers"
                icon="info"
              >
                {attentionProjects.length > 0 ? (
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
                  <Text>All projects have moved beyond draft state.</Text>
                )}
              </WidgetShell>
            </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="d-flex col-12 container flex-column align-items-center justify-content-center">
          <StartProjectButton
            setModalComponent={setModalComponent}
            id={"dashboardStartProject"}
          />
        </div>
      )}

      {modalComponent}
    </>
  );
};

export default Home;
