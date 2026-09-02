export async function loadInteractiveArtifacts({
  loadPmtiles,
  loadSidecar,
  signal,
}) {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });

  const invoke = (loader) => {
    try {
      return Promise.resolve(loader(controller.signal));
    } catch (error) {
      return Promise.reject(error);
    }
  };

  try {
    const [pmtilesHeader, sidecar] = await Promise.all([
      invoke(loadPmtiles),
      invoke(loadSidecar),
    ]);
    return { pmtilesHeader, sidecar };
  } catch (error) {
    controller.abort();
    throw error;
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}