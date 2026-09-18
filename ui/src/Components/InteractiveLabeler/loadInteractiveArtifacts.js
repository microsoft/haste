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

  const pmtilesPromise = invoke(loadPmtiles);
  const sidecarPromise = invoke(loadSidecar);
  try {
    const [pmtilesHeader, sidecar] = await Promise.all([
      pmtilesPromise,
      sidecarPromise,
    ]);
    return { pmtilesHeader, sidecar };
  } catch (error) {
    controller.abort();
    await Promise.allSettled([pmtilesPromise, sidecarPromise]);
    throw error;
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}