const STATUS_DISPLAY = {
  PENDING: { label: "Queued", color: "warning" },
  IN_PROGRESS: { label: "Publishing", color: "warning" },
  PUBLISHED: { label: "Published", color: "success" },
  FAILED: { label: "Failed", color: "danger" },
  UNPUBLISH_PENDING: { label: "Cleanup queued", color: "warning" },
  UNPUBLISHING: { label: "Unpublishing", color: "warning" },
  UNPUBLISH_FAILED: { label: "Cleanup failed", color: "danger" },
};

const ACTIVE_STATUSES = new Set([
  "PENDING",
  "IN_PROGRESS",
  "UNPUBLISH_PENDING",
  "UNPUBLISHING",
]);


export function isPublishingStatusActive(status) {
  return ACTIVE_STATUSES.has(status);
}

export function getPublishingStatusDisplay(status) {
  return STATUS_DISPLAY[status] || { label: status, color: "informative" };
}

export function selectSupportedArtifacts(options, provider) {
  const supported = new Set(provider?.supportedArtifactKinds || []);
  return (options?.availableArtifacts || [])
    .filter((artifact) => supported.has(artifact.kind))
    .map((artifact) => artifact.kind);
}

// Summarize source-imagery references into per-program display rows
// (deduped by program) for the publish/edit dialogs.
export function summarizeSourceImagery(refs) {
  const byProgram = new Map();
  for (const ref of refs || []) {
    const key = ref.programId || ref.programName || "";
    const entry = byProgram.get(key) || {
      program: ref.programName || key,
      license: ref.license || "",
      count: 0,
    };
    entry.count += 1;
    byProgram.set(key, entry);
  }
  return [...byProgram.values()];
}