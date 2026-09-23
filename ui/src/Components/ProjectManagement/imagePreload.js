export function preloadImage(
  url,
  onResult,
  { fetchImage = fetch, createImage = () => new Image(), objectUrls = URL } = {}
) {
  const controller = new AbortController();
  const { signal } = controller;
  const image = createImage();
  let objectUrl = null;

  const report = (status, loadedUrl = null) => {
    if (!signal.aborted) onResult({ status, loadedUrl, signal });
  };
  const releaseObjectUrl = () => {
    if (objectUrl) objectUrls.revokeObjectURL(objectUrl);
    objectUrl = null;
  };
  const display = (source) => {
    if (signal.aborted) return;
    image.onload = () => report("loaded", source);
    image.onerror = () => {
      releaseObjectUrl();
      report("error");
    };
    image.src = source;
  };

  const load = async () => {
    let response;
    try {
      response = await fetchImage(url, { signal });
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof TypeError) {
        display(url);
      } else {
        report("error");
      }
      return;
    }

    try {
      signal.throwIfAborted();
      if (!response.ok) throw new Error("Image could not be loaded.");
      const blob = await response.blob();
      signal.throwIfAborted();
      objectUrl = objectUrls.createObjectURL(blob);
      display(objectUrl);
    } catch {
      releaseObjectUrl();
      report("error");
    }
  };
  load();

  return () => {
    controller.abort();
    image.onload = null;
    image.onerror = null;
    image.removeAttribute("src");
    releaseObjectUrl();
  };
}