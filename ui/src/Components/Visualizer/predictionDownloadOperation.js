// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// A single cancellable read per raw-download control. No version discovery,
// writes, retries, query additions or global download-helper changes.
export function createPredictionDownloadOperation(download, onChange) {
  let active = null;
  return {
    run(url) {
      if (active) return active.promise;
      const controller = new AbortController();
      const operation = { controller };
      active = operation;
      operation.promise = Promise.resolve().then(async () => {
        try {
          controller.signal.throwIfAborted();
          await download(url, 0, { signal: controller.signal });
          if (controller.signal.aborted) return { cancelled: true };
          if (active === operation) onChange({ loading: false, error: "" });
          return { ok: true };
        } catch (cause) {
          if (controller.signal.aborted) return { cancelled: true };
          const error = cause.message || "The prediction download failed.";
          if (active === operation) onChange({ loading: false, error });
          return { error };
        } finally {
          if (active === operation) active = null;
        }
      });
      onChange({ loading: true, error: "" });
      return operation.promise;
    },
    cancel() {
      const operation = active;
      active = null;
      operation?.controller.abort();
    },
  };
}
