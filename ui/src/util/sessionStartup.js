const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const RETRY_DELAYS_MS = [200, 500];

function isRetryable(error) {
  return (
    error?.name === "NetworkRequestError" ||
    RETRYABLE_STATUSES.has(error?.status)
  );
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function makeDiagnosticReference() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function getFailureKind(error) {
  if (error?.status === 401) return "unauthorized";
  if (error?.status === 403) return "forbidden";
  if (error?.name === "NetworkRequestError") return "network";
  if (error?.status >= 500 || RETRYABLE_STATUSES.has(error?.status)) {
    return "service";
  }
  return "unknown";
}

export async function loadSession({
  validateUser,
  setAppParams,
  setSessionError,
  waitImpl = wait,
  retryDelaysMs = RETRY_DELAYS_MS,
  now = () => new Date(),
  createDiagnosticReference = makeDiagnosticReference,
}) {
  setSessionError(null);
  let error;

  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
    try {
      await validateUser(setAppParams);
      return true;
    } catch (caught) {
      error = caught;
      if (attempt >= retryDelaysMs.length || !isRetryable(error)) break;
      await waitImpl(retryDelaysMs[attempt]);
    }
  }

  setAppParams((previous) => ({
    ...previous,
    userId: null,
    identityId: null,
    userRoles: [],
    userSettings: {},
    userStatus: null,
    publishingEnabled: false,
    publishingProviders: [],
  }));
  setSessionError({
    kind: getFailureKind(error),
    status: Number.isInteger(error?.status) ? error.status : null,
    reference: createDiagnosticReference(),
    timestamp: now().toISOString(),
  });
  return false;
}
