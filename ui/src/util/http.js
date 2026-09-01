// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export async function fetchJsonResponse(url, options = {}, fetchImpl = fetch) {
  const response = await fetchImpl(url, options);
  const etag = response.headers?.get?.("etag") ?? null;

  if (response.status === 304) {
    return { data: null, etag, status: response.status };
  }
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const data = response.status === 204 ? null : await response.json();
  return { data, etag, status: response.status };
}