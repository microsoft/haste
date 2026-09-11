// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export function createSingleFlight() {
  let active = null;

  return {
    run(key, task) {
      if (active?.key === key) return active.promise;
      active?.controller.abort();

      const controller = new AbortController();
      const entry = { controller, key, promise: null };
      entry.promise = Promise.resolve()
        .then(() => task(controller.signal))
        .finally(() => {
          if (active === entry) active = null;
        });
      active = entry;
      return entry.promise;
    },

    abort() {
      active?.controller.abort();
      active = null;
    },

    isRunning(key) {
      return active !== null && (key === undefined || active.key === key);
    },
  };
}