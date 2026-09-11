// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

function isExpectedNavigationAbort(request, priorNavigationRequests = new Set()) {
  if (!priorNavigationRequests.has(request)) return false;
  const failure = request.failure();
  const errorText = String(failure?.errorText || "").toLowerCase();
  return errorText.includes("err_aborted") || errorText.includes("aborterror");
}

module.exports = { isExpectedNavigationAbort };
