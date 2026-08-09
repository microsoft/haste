// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { createContext, useCallback, useState } from "react";
import PropTypes from "prop-types";

// eslint-disable-next-line react-refresh/only-export-components
export const AppContext = createContext();

export const AppProvider = ({ children }) => {
  const guidedTourList = [
    {
      name: "dashboardGuide",
      cookieName: "generalGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#dashboardStartProject`,
          title: "Start Project",
          content:
            "A project is a way to organize image layers for conducting damage assessments. Click this button to start a new project.",
        },
      ],
    },    
    {
      name: "singleProjectModelGuide",
      cookieName: "generalGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#singleModelTrainStatus0`,
          title: "Model Training Status",
          content:
            "This shows the status of model training. Click on the \"i\" to see detailed logs of the training job.",
        },
        {
          type: "teachingBubble",
          target: `#singleModelResults0`,
          title: "Model Results",
          content:
            "If the inference was successful, the model results will be available here. Click on this button to view or download the results.",
        },
        {
          type: "teachingBubble",
          target: `#singleModelMoreOptions0`,
          title: "Additional model options",
          content:
            "Click this button for more options.",
        }        
      ],
    },    
    {
      name: "createEditModelTrainingModalGuide",
      cookieName: "generalGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#createEditModelTrainingBaseModel`,
          title: "Base Model",
          content:
            "The base model is the pre-trained model that will be used as a starting point for training yours. Expand the dropdown to see available models.",
        },
        {
          type: "teachingBubble",
          target: `#createEditModelTrainingParams`,
          title: "Params",
          content:
            "Click this button to view the training hyperparameters. Use the provided defaults or edit them in place.",
        }
      ],
    },
    {
      name: "singleProjectGuide",
      cookieName: "generalGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#singleProjectCreateImageLayer`,
          title: "Create Image Layer",
          content:
            "An image layer contains pre and post event imagery files. Click the button to start adding imagery files.",
        },
        {
          type: "teachingBubble",
          target: `#singleProjectTable`,
          title: "Image Layer List",
          content:
            "This table shows the list of Image Layers for this project.",
        },
        {
          type: "teachingBubble",
          target: `#singleProjectMoreOptions0`,
          title: "More Options",
          content: "Use this button to edit Image Layer details or delete the Image Layer.",
        },
      ],
    },
    {
      name: "projectsGuide",
      cookieName: "generalGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#projectsStartProject`,
          title: "Start Project",
          content:
            "A project is a way to organize image layers for conducting damage assessments. Click this button to start a new project.",
        },
        {
          type: "teachingBubble",
          target: `#projectsTable`,
          title: "Project List",
          content:
            "This table shows the list of projects. Click on a project to see its details.",
        },
        {
          type: "teachingBubble",
          target: `#projectsMoreOptions0`,
          title: "More Options",
          content: "Use this button to edit Project details or delete the Project.",
        },
      ],
    },
    {
      name: "labelingToolGuide",
      cookieName: "labellingToolGuidedTour",
      steps: [
        {
          type: "teachingBubble",
          target: `#imageryControlsButton`,
          title: "Imagery properties",
          content:
            "Open the imagery controls to adjust image properties and switch imagery layers.",
        },
        {
          type: "teachingBubble",
          target: `#postEventImagery`,
          title: "Imagery toggle",
          content:
            "Click on the toggle to switch between post event and pre event imagery. If you did not upload pre event imagery, the tool will default to Azure Basemap. You can also use the keyboard shortcut - Ctrl+Alt+c",
        },
        {
          type: "teachingBubble",
          target: `#drawingToolbar`,
          title: "Drawing tools",
          content:
            "Select a shape to start drawing. Click on the delete icon to remove any label you do not want. To edit the primary class of a label, click on the pencil icon, select a label, and then change the primary class using the primary class selector.",
        },          
        {
          type: "teachingBubble",
          target: `.labeling-class-trigger`,
          title: "Primary Classes",
          content:
            "Switch between label classes here. You must select a tool as well as a class to draw a label. ",
        },              
        {
          type: "teachingBubble",
          target: `#saveAndTrainButton`,
          title: "Saving Labels",
          content:
            "Click on \"Save\" to save all labels drawn so far. Alternatively, click on the down arrow next to \"Save\" to save labels and initiate model training in one click."
        },        
        {
          type: "fixed",
          target: "bottom-right",
          title: "Dense clustered Labelling.",
          content:
            "Label features that are directly adjacent to each other. For example, if you are labeling a building, then label the background area around it as well. This is important because unlabeled areas are not used in training the model, therefore if you label a building, but do not label around it, then model will not be penalized for making a large blurry prediction around the building (vs. a precise prediction that follows the lines of the building).",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Dense clustered Labelling.",
          content:
            "​<img src='../../assets/img/guidedTours/drawing/denseClusteredLabelling1.jpg' alt='Dense clustered Labelling (Correct)' style='width:100%' />​",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Dense clustered Labelling.",
          content:
            "<img src='../../assets/img/guidedTours/drawing/denseClusteredLabelling2.jpg' alt='Dense clustered Labelling (Wrong: Sparse labels)' style='width:100%' />",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "High Precision Labelling.",
          content:
            "Labeling features with high precision is more important than rapidly labeling large areas with low precision​<br/>​<br/><img src='../../assets/img/guidedTours/drawing/highPrecisionLabelling1.jpg' alt='High Precision Labelling (Correct​)' style='width:100%' />​​",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "High Precision Labelling.",
          content:
            "Labeling features with high precision is more important than rapidly labeling large areas with low precision​<br/><br/><img src='../../assets/img/guidedTours/drawing/highPrecisionLabelling2.jpg' alt='High Precision Labelling (Wrong: Low precision labels)' style='width:100%' />​​",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Maximize diversity of labels.",
          content:
            "Label diverse features. For example, labeling 20 identical looking buildings is less useful to the model training as opposed labelling 20 buildings with varying roof colors, sizes and textures<br/><br/><img src='../../assets/img/guidedTours/drawing/maximizeDiversityOfLabels1.jpg' alt='Maximize diversity of labels (High building diversity​)' style='width:100%' />",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Maximize diversity of labels.",
          content:
            "Label diverse features. For example, labeling 20 identical looking buildings is less useful to the model training as opposed labelling 20 buildings with varying roof colors, sizes and textures<br/><br/><img src='../../assets/img/guidedTours/drawing/maximizeDiversityOfLabels2.jpg' alt='Maximize diversity of labels (Low building diversity​)' style='width:100%' />",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Label relevant portions only.",
          content:
            "Buildings can have mixed labels e.g. a partially damaged building will have some pixels represented the damaged class while other pixels will not. When labelling, only assign the damaged pixels to the damaged class as opposed to the whole building.<br/><br/><img src='../../assets/img/guidedTours/drawing/labelRelevantPortionsOnly1.jpg' alt='Label relevant portions only (Correct)​' style='width:100%' />",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Label relevant portions only.",
          content:
            "Buildings can have mixed labels e.g. a partially damaged building will have some pixels represented the damaged class while other pixels will not. When labelling, only assign the damaged pixels to the damaged class as opposed to the whole building.<br/><br/><img src='../../assets/img/guidedTours/drawing/labelRelevantPortionsOnly2.jpg' alt='Label relevant portions only (Wrong: Labelling non-damaged pixels as damaged​)​' style='width:100%' />",
        },
        {
          type: "fixed",
          target: "bottom-right",
          title: "Additional tips",
          content: "Do not label a feature that you are uncertain about",
        },
        {
          type: "teachingBubble",
          target: "#backButton",
          title: "Exit Labeling Tool",
          content:
            "Click \"Back\" to exit the labeling tool ",
        },         
        {
          type: "teachingBubble",
          target: `#helpButton`,
          title: "Help Button",
          content: "Click this button to restart the guided tour at any time.",
        },
      ],
    },
  ];

  const [appParams, setAppParams] = useState({
    appTitle: "HASTE",
    visualizerTitle: "",
    dialogParams: {},
    userId: null,
    userRoles: null,
    userSettings: null,
    userStatus: null,
    identityId: null,
    publishingEnabled: false,
    publishingProviders: [],
    isLoading: false,
    loadingMessage: "",
    appHeaderRightButtons: [],
    guidedTourProperties: guidedTourList,
    currentTour: null,
    currentTourStep: 1,
    bootstrapBreakpoint: "",
  });

  function updateAppParams(newParams) {
    setAppParams((prevParams) => ({
      ...prevParams,
      ...newParams,
    }));
  }

  const setIsLoading = useCallback((isLoading, message = "Loading...") => {
    setAppParams((prevParams) => ({
      ...prevParams,
      isLoading: isLoading,
      loadingMessage: message,
    }));
  }, []);

  const setAppHeaderRightButtons = useCallback((appHeaderRightButtons) => {
    setAppParams((prevParams) => ({
      ...prevParams,
      appHeaderRightButtons: appHeaderRightButtons,
    }));
  }, []);

  function setCurrentTour(currentTourName) {
    const currentTourTemp = guidedTourList.find(
      (tour) => tour.name === currentTourName
    );

    setAppParams((prevParams) => ({
      ...prevParams,
      currentTour: currentTourTemp,
    }));
  }

  function setCurrentTourStep(currentTourStep) {
    setAppParams((prevParams) => ({
      ...prevParams,
      currentTourStep: currentTourStep,
    }));
  }

  function setDialog(title, subText, buttons) {
    setAppParams((prevParams) => ({
      ...prevParams,
      dialogParams: {
        title,
        subText,
        buttons,
      },
    }));
  }

  function initCurrentTour(currentTourName, step = 1) {
    setTimeout (() => {
      setCurrentTour(currentTourName);
      setCurrentTourStep(step);  
    }, 100);
  }

  return (
    <AppContext.Provider
      value={{
        appParams,
        setAppParams,
        setDialog,
        setIsLoading,
        updateAppParams,
        setAppHeaderRightButtons,
        initCurrentTour,
        setCurrentTourStep,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

AppProvider.propTypes = {
  children: PropTypes.node.isRequired,
};
