export function isAbortError(error) {
  return error?.name === "AbortError";
}

export function shouldAppendSubscriptionKey(apiUrl, subscriptionKey) {
  return Boolean(
    subscriptionKey && /^https:\/\//i.test(apiUrl || "")
  );
}

export function apiFetch(url, requestOptions = {}) {
  return fetch(url, requestOptions);
}