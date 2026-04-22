// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { PrimaryButton, Text } from "@fluentui/react";
import OpenProject from "./Home/OpenProject";
import { useState, useEffect, useContext } from "react";

import { AppContext } from "../AppContext";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../util/api";
import { setGuidedTourState, initGuidedTourState } from "./GuidedTourHelper";

import StartProjectButton from "./StartProjectButton";

const Home = () => {
  const navigate = useNavigate();
  const { setIsLoading, initCurrentTour, setAppHeaderRightButtons, appParams, setAppParams } =
    useContext(AppContext);
  const [dashboardData, setDashboardData] = useState(null);
  const [modalComponent, setModalComponent] = useState(null);

  useEffect(() => {
    const fetchProjects = async () => {
      setIsLoading(true);
      try {
        const response = await apiGet("GetDashboardData");
        setDashboardData(response);
      } catch (error) {
        console.error("Error fetching projects:", error);
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

  return (
    <>
      {dashboardData.projects.length > 0 ? (
        <div className="d-flex col-12 container flex-column align-items-center justify-content-md-center p-0 p-md-4 pt-4 m-md-5">
          <div className="row w-100 mb-3">
            <div className="d-flex col-12">
              <StartProjectButton
                setModalComponent={setModalComponent}
                id={"dashboardStartProject"}
              />
            </div>
          </div>
          <div className="row w-100">
            {/* First Column */}
            <div className="col-12 col-xl flex-grow-1">
              {/* Open Projects */}
              <div className="col-12 p-4 home-box mb-3">
                <h5 className="home-title">Recent Projects</h5>
                {dashboardData.projects.slice(0, 3).map((project, index) => (
                  <OpenProject
                    key={project.projectId}
                    openProject={project}
                    index={index}
                  />
                ))}
              </div>
              <div className="col-12">
                {dashboardData.projects.length > 0 && (
                  <h5>
                    <PrimaryButton
                      text="Show more Projects"
                      onClick={() => navigate("/projects")}
                    />
                  </h5>
                )}
              </div>
            </div>

            {/* Second Column */}
            <div className=" col-12 col-xl-3 p-0 ps-3 pe-3 pt-3 pt-xl-0 ps-xl-4 pe-xl-0 pb-4">
              <Text variant="large" className="mb-3">
                <span className="fw-semibold">
                  <b>H</b>igh-speed <b>A</b>ssessment and <b>S</b>atellite{" "}
                  <b>T</b>racking for <b>E</b>mergencies{" "}
                </span>
                is an AI-powered tool designed by the{" "}
                <span className="fw-semibold">Microsoft AI for Good Lab </span>
                to quickly identify and evaluate structural damage to buildings
                after a catastrophe.
                <br />
                <br />
                Leveraging advanced image analysis and machine learning, it
                empowers emergency responders and authorities to prioritize
                critical areas, accelerate recovery efforts, and enhance safety
                assessments.
              </Text>
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
