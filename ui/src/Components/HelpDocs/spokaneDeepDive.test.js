import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import {
  spokaneDeepDiveEpisodes,
  spokaneDeepDiveMediaBase,
} from "./spokaneDeepDiveEpisodes.js";

test("walkthrough defines all six episode anchors in published order", () => {
  assert.deepEqual(
    spokaneDeepDiveEpisodes.map(({ id }) => id),
    [
      "introduction",
      "standard-labeling",
      "building-embeddings",
      "editing-predictions",
      "understanding-outputs",
      "open-data-catalog",
    ]
  );
  assert.equal(new Set(spokaneDeepDiveEpisodes.map(({ file }) => file)).size, 6);
});

test("every episode reuses existing recordings, previews, and WebVTT captions", () => {
  const mediaDirectory = new URL(
    "../../../../docs/_static/usage/spokane-deep-dive/",
    import.meta.url
  );
  for (const episode of spokaneDeepDiveEpisodes) {
    for (const extension of ["mp4", "jpg", "vtt"]) {
      assert.ok(
        existsSync(new URL(`${episode.file}.${extension}`, mediaDirectory)),
        `${episode.file}.${extension} must exist`
      );
    }
    assert.match(
      readFileSync(new URL(`${episode.file}.vtt`, mediaDirectory), "utf8"),
      /^WEBVTT/
    );
  }
});

test("episode titles and durations stay consistent with the published walkthrough", () => {
  const guide = readFileSync(
    new URL("../../../../docs/usage/spokane-deep-dive.md", import.meta.url),
    "utf8"
  );
  for (const episode of spokaneDeepDiveEpisodes) {
    assert.ok(episode.title.length > 0);
    assert.ok(episode.description.length > 0);
    assert.ok(guide.includes(`${episode.file}.mp4`));
    assert.ok(guide.includes(episode.duration));
    assert.match(episode.duration, /^\d+:[0-5]\d$/);
  }
});

test("episode media uses the existing HTTPS documentation host", () => {
  assert.equal(
    spokaneDeepDiveMediaBase,
    "https://microsoft.github.io/haste/_static/usage/spokane-deep-dive"
  );
});
