import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

for (const [component, expectedVideos] of [
  ["HelpDocsOverview.jsx", 1],
  ["HelpDocsProjects.jsx", 3],
  ["HelpDocsImageLayers.jsx", 3],
]) {
  test(`${component} pairs every existing video with its own lightweight preview`, () => {
    const componentUrl = new URL(component, import.meta.url);
    const source = readFileSync(componentUrl, "utf8");
    const imports = new Map(
      [...source.matchAll(/import (\w+) from ['"]([^'"]+)['"];/g)]
        .map((match) => [match[1], match[2]])
    );
    const videos = [...source.matchAll(/<video\b[^>]*>/g)];
    assert.equal(videos.length, expectedVideos);

    for (const [video] of videos) {
      const videoBinding = video.match(/src=\{(\w+)\}/)?.[1];
      const posterBinding = video.match(/poster=\{(\w+)\}/)?.[1];
      const videoPath = imports.get(videoBinding);
      const posterPath = imports.get(posterBinding);
      assert.ok(videoPath?.endsWith(".mp4"));
      assert.equal(posterPath, videoPath.replace(/\.mp4$/, ".jpg"));
      assert.match(video, /preload="none"/);
      assert.match(video, /\bcontrols\b/);

      const poster = readFileSync(new URL(posterPath, componentUrl));
      assert.deepEqual([...poster.subarray(0, 3)], [0xff, 0xd8, 0xff]);
      assert.ok(poster.length < 64 * 1024, "Preview must be smaller than 64 KiB");
    }
  });
}
