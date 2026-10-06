// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export class HttpResponseError extends Error {
  constructor(status) {
    super(`HTTP error! status: ${status}`);
    this.name = "HttpResponseError";
    this.status = status;
  }
}

export class NetworkRequestError extends Error {
  constructor(cause) {
    super("Network request failed.", { cause });
    this.name = "NetworkRequestError";
  }
}

export async function fetchJsonResponse(url, options = {}, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(url, options);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new NetworkRequestError(error);
  }
  const etag = response.headers?.get?.("etag") ?? null;

  if (response.status === 304) {
    return { data: null, etag, status: response.status };
  }
  if (!response.ok) {
    throw new HttpResponseError(response.status);
  }

  const data = response.status === 204 ? null : await response.json();
  return { data, etag, status: response.status };
}