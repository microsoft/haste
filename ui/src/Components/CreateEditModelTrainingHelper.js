// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { apiGet } from "../util/api";

export async function createComponentDefaultState(modelToEdit, imageLayer, projectId, eventTypes) {
  try {

    var  eventTypesL = "eventTypes=" + eventTypes;
    var imagerySource = "";

    if (imageLayer.sourceTypePostEvent !== "" && imageLayer.sourceTypePostEvent !== null && imageLayer.sourceTypePostEvent !== undefined) {
      var concatChar = eventTypesL === "" ? "" : "&";
      eventTypesL += concatChar + "imagerySource=" + imageLayer.sourceTypePostEvent;
    }

    var cataloguedModels = [];

    
    await apiGet(`GetModelCatalog?${eventTypesL}${imagerySource}`)
      .then((response) => {
        cataloguedModels.push(
          ...response.modelCatalog.map((model) => ({
            key: model.modelId,
            text: model.baseModelName,
            value: model
          }))
        );
      })
      .catch((error) => {
        console.error("Error fetching model catalog:", error);
      });

    

    const tempState = modelToEdit
      ? {
        ...modelToEdit,
        nameError: "",
        viewParams: false,
        learningRateError: "",
        batchSizeError: "",
        maxEpochsError: "",
        cataloguedModels: cataloguedModels
        
      }
      : {
        modelId: "",
        projectId: projectId,
        imageLayerId: imageLayer.imageLayerId,
        name: imageLayer.name + "-model-" + Math.floor(Math.random() * 1000),
        nameError: "",
        autoRunInference: true,
        viewParams: false,
        learningRate: "0.0001",
        learningRateError: "",
        batchSize: "32",
        batchSizeError: "",
        maxEpochs: "3",
        maxEpochsError: "",
        initialWeightsUrl: "",
        cataloguedModels: cataloguedModels
      }

    return tempState;
  } catch (error) {
    console.error("Error inializing component:", error);
  }

}


export const onFormChange = (value, key, setComponentState, componentState) => {
  if (key === "viewParams") {
    setComponentState({
      ...componentState,
      viewParams: !componentState.viewParams,
    });
  } else {
    setComponentState({ ...componentState, [key]: value });
  }
};