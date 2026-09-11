// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Testable save/display boundary, used by the editor hook. A failed GET after a
// committed PUT is not a failed save and must never trigger another PUT.
export async function publishPredictionEdit(body, { write, loadVersion, onSaved, buildingCount, isCurrent = () => true }) {
  const result = await write(body);
  if (!Number.isSafeInteger(result?.version) || result.version <= 0 ||
      result.predictionRevision !== body.predictionRevision ||
      !Number.isSafeInteger(result.buildingCount) || result.buildingCount < 0 ||
      (buildingCount !== undefined && result.buildingCount !== buildingCount) ||
      !Number.isSafeInteger(result.editedCount) || result.editedCount < 0 || result.editedCount > result.buildingCount ||
      !result.gpkgUrl || !result.predictionAttrsUrl) {
    throw new Error("The server did not confirm a matching saved version and paired artifacts.");
  }
  if (!isCurrent()) throw new DOMException("Save view cancelled.", "AbortError");
  onSaved(result);
  try {
    const candidate = await loadVersion(result.version, result.predictionRevision);
    if (!isCurrent()) throw new DOMException("Saved version display cancelled.", "AbortError");
    return { result, candidate };
  } catch (error) {
    if (!isCurrent()) throw error;
    return { result, displayError: `Version ${result.version} was saved but could not be displayed. ${error.message}` };
  }
}
