import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const helpFiles = [
  "HelpDocsImageLayers.jsx",
  "HelpDocsLabeling.jsx",
  "HelpDocsModelCatalog.jsx",
  "HelpDocsModelTraining.jsx",
  "HelpDocsOverview.jsx",
  "HelpDocsProjects.jsx",
  "HelpDocsResults.jsx",
];

test("help images and videos defer media downloads", async () => {
  const sources = await Promise.all(
    helpFiles.map((file) =>
      readFile(new URL(`./HelpDocs/${file}`, import.meta.url), "utf8")
    )
  );
  const markup = sources.join("\n");
  const images = markup.match(/<img\b[^>]*>/g) || [];
  const videos = markup.match(/<video\b[^>]*>/g) || [];

  assert.ok(images.length > 0);
  assert.ok(videos.length > 0);
  images.forEach((image) => {
    assert.match(image, /\bloading="lazy"/);
    assert.match(image, /\bdecoding="async"/);
  });
  videos.forEach((video) => assert.match(video, /\bpreload="none"/));
});