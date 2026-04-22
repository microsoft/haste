// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.


export function validateEmpty(key, value) {
  if (typeof value === "string" && value.trim() === "") {
    return `${key} can't be empty`;
  }

  if (value instanceof Date) {
    if (isNaN(value.getTime())) {
      return `${key} is not a valid date`;
    }
  }

  return "";
}


export function validateEmptyOrInvalid(isRequired = true, key, value) {
  var error = ""
  if (isRequired) {
    error = validateEmpty(key, value);
  }else{
    if (value === "") {
      return "";
    }
  }


  if (error === "") {
    const regex = /^[a-zA-Z0-9 ,._-]+$/;

    if (!regex.test(value)) {
      error = `${key} only allows letters, numbers, spaces, underscores, and hyphens`;
    }
  }

  return error;
}



export function validateAtLeastSomeNumber(key, value, number) {

  if (value.length < number) {
    return `${key} must have at least ${number} element${number > 1 ? "s" : ""}`;
  }
  return "";
}

export function validateIsUploading(preEventImageryUrls, postEventImageryUrls) {
  for (let i = 0; i < preEventImageryUrls.length; i++) {
    if (preEventImageryUrls[i].type === "file") {
      return true;
    }
  }

  for (let i = 0; i < postEventImageryUrls.length; i++) {
    if (postEventImageryUrls[i].type === "file") {
      return true;
    }
  }

  return false;
}

export function validatePrimaryClasses(primaryClasses) {

  if (primaryClasses.length === 0) {
    return "At least one primary class is required";
  }

  for (let i = 0; i < primaryClasses.length; i++) {
    if (primaryClasses[i].name === "" || primaryClasses[i].color === "") {
      return "Primary classes must have a name and a color";
    }
  }

  const names = primaryClasses
    .map(pc => pc.name.trim().toLowerCase())
    .filter(name => name !== "");
  const uniqueNames = new Set(names);
  if (names.length !== uniqueNames.size) {
    return "Primary classes contain repeated names";
  }

  return false;
}

export function validateEventTypes(eventTypes){

  if(eventTypes.length === 0){
    return "At least one event type is required";
  }

  return false;
}

export function validateURL(url) {
  if (url.trim() === "") {
    return [false, "URL can't be empty"];
  } else {
    try {
      new URL(url);
      return [true, ""];
    } catch (e) {
      return [false, "Invalid URL format"];
    }
  }
}


export function validateFileType(file, acceptedFileTypes) {
  const fileExtension = file.split(".").pop().toLowerCase();
  const fileName = file.split("/").pop();
  if(acceptedFileTypes.includes(fileExtension)){
    return [true, ""];
  }else{
    return [false, `File ${fileName} is not of type ${acceptedFileTypes.join(", ")}`];
  }
}



export function validateEmail(key, value) {
  if (!value) {
    return `${key}'s email can't be empty`;
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!emailRegex.test(value)) {
    return "Invalid e-mail format";
  }

  return "";
}

export function validateTimestamp(line){
  const regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+\d{2}:\d{2}/;
  return regex.test(line);
}

export function validateInt(key, value){
  var error = validateEmpty(key, value);
  if (error === "") {
    const regex = /^[0-9]+$/;
    if (!regex.test(value)) {
      error = `${key} must be an integer number`;
    }
  }
  return error;
}

export function validateFloat(key, value){
  var error = validateEmpty(key, value);
  if (error === "") {
    const regex = /^[0-9]+(\.[0-9]+)?$/;
    if (!regex.test(value)) {
      error = `${key} must be a float number`;
    }
  }
  return error;
}

export function validateRepeatedKeyInArray(key, array){

  for (let i = 0; i < array.length; i++) {
    if(array[i].key === "" || array[i].value === ""){
      return `Every ${key} line must have a key and a value`;
    }
  }

  const keys = array.map(item => item.key.trim()).filter(item => item !== "");
  const uniqueKeys = new Set(keys);
  if(keys.length !== uniqueKeys.size){
    return `${key} contains repeated keys`;
  }
  return "";
}