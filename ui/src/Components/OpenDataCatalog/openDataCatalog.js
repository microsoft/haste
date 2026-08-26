// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Open Data Catalog — discover + fetch + normalize open disaster-response
// imagery from the Vantor Open Data Program (S3 STAC) and the Planet
// Open Data Program (Source Cooperative STAC). Adapted from the standalone
// prototype (Open Disaster Response Data Visualizer):
// https://visualizers.aiforgood.ai/damage-assessment/venezuela_earthqake_data_explorer.html
//
// This module is deliberately framework-free (no React, no atlas): it is the
// single seam where the catalog is produced. Today it runs client-side; the
// `discoverEvents()` / `fetchEventCatalog(event)` contract can later be moved
// behind an Azure Function with no change to the UI components that consume
// it. See spec/features/open-data-catalog/.

// Root STAC catalogs that enumerate every available disaster event.
const VANTOR_ROOT_CATALOG =
  "https://vantor-opendata.s3.amazonaws.com/events/catalog.json";
const PLANET_ROOT_CATALOG =
  "https://data.source.coop/planet/disasterdata/catalog.json";

export const SOURCE_COLORS = { Vantor: "#0078d4", Planet: "#00b294" };

// Open-data program registry, keyed by a scene's `source`. Mirrors the backend
// OPEN_DATA_PROGRAMS (hastegeo.core.publishing.open_data). Only scenes from a
// program here are captured as attributable source-imagery references; the
// backend re-validates programId and is authoritative on name/license.
export const OPEN_DATA_PROGRAMS = {
  Vantor: {
    programId: "vantor-open-data",
    programName: "Vantor Open Data Program",
    license: "CC-BY-NC-4.0",
  },
  Planet: {
    programId: "planet-open-data",
    programName: "Planet Disaster Data",
    license: "CC-BY-NC-4.0",
  },
};

// Build a source-imagery reference from a catalog scene (or null if the scene
// is not from a registered open-data program or has no STAC item href). The
// `sourceUrl` field is UI-only (correlates the ref with the added COG for
// removal); the backend ignores it.
export function sourceImageryRef(scene, phase) {
  const program = OPEN_DATA_PROGRAMS[scene?.source];
  if (!program || !scene?.itemHref) return null;
  return {
    programId: program.programId,
    programName: program.programName,
    sceneId: scene.id || "",
    title: scene.title || scene.id || "",
    href: scene.itemHref,
    license: program.license,
    attributable: true,
    phase: phase || scene.phase || null,
    capturedDate: scene.datetime || null,
    sourceUrl: scene.cogUrl || "",
  };
}

// Maps a normalized scene to the HASTE source-type dropdown key
// (see sourceTypeOptions in CreateEditImageLayerHelper.js).
const SOURCE_TYPE_KEYS = {
  vantor: "vantor",
  planetSkysat: "planet_skysat",
  planet: "planet_scope",
};

// ── COG preview tiles (TiTiler) ─────────────────────────────────────────────
//
// HASTE runs a TiTiler instance that streams tiles from any remote COG, reached
// from the browser through the api-proxy at VITE_TITILER_URL (…/api/titiler/).
// This lets the explorer preview a scene's actual imagery on the map without an
// Azure Maps subscription. Returns an Azure-Maps-style {z}/{x}/{y} template.
function titilerBase() {
  const raw =
    (typeof import.meta !== "undefined" && import.meta.env?.VITE_TITILER_URL) ||
    "/api/titiler/";
  return raw.replace(/\/+$/, "");
}

export function titilerTileUrl(cogUrl) {
  if (!cogUrl) return null;
  // Use the same canonical tile path the rest of HASTE uses (labels.py /
  // function_app.py): the WebMercatorQuad TileMatrixSet segment is required by
  // the deployed TiTiler/APIM route. The plain /cog/tiles/{z}/{x}/{y} alias
  // works on the local titiler but 404s in production.
  return `${titilerBase()}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?scale=1&url=${encodeURIComponent(
    cogUrl
  )}`;
}

// Maximum width/height (px) of a clipped export. A clip at native GSD over a
// large box would be enormous (an 8k² RGB GeoTIFF is ~190 MB) and TiTiler
// can't generate + stream it from the remote COG before the proxy's timeout,
// yielding a 504. Cap the longest side so the crop stays fast and a
// reasonable upload size; TiTiler downscales larger areas.
const CLIP_MAX_DIM = 4096;

// Build a TiTiler crop URL that returns a georeferenced GeoTIFF of `bbox`
// ([west, south, east, north], EPSG:4326) from `cogUrl`, sized to roughly the
// scene's native resolution (`gsd`, metres/px) up to CLIP_MAX_DIM.
export function titilerCropUrl(cogUrl, bbox, gsd) {
  if (!cogUrl || !bbox || bbox.length < 4) return null;
  const [w, s, e, n] = bbox;
  const midLat = (s + n) / 2;
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos((midLat * Math.PI) / 180);
  const res = gsd && gsd > 0 ? gsd : 0.5;
  let width = Math.max(1, Math.round(((e - w) * mPerDegLon) / res));
  let height = Math.max(1, Math.round(((n - s) * mPerDegLat) / res));
  const scale = Math.min(1, CLIP_MAX_DIM / Math.max(width, height));
  width = Math.max(1, Math.round(width * scale));
  height = Math.max(1, Math.round(height * scale));
  const box = [w, s, e, n].map((v) => v.toFixed(8)).join(",");
  return `${titilerBase()}/cog/crop/${box}/${width}x${height}.tif?url=${encodeURIComponent(
    cogUrl
  )}`;
}

export function clipFileName(scene) {
  const base = (scene?.id || "scene").replace(/[^A-Za-z0-9_-]+/g, "_");
  return `${base}_clip.tif`;
}

// ── AOI overlap helpers (bbox = [west, south, east, north]) ─────────────────
//
// Used to filter the catalog to scenes that actually cover the drawn clip AOI:
// a scene whose footprint doesn't overlap the layer-level AOI contributes
// nothing to the clipped mosaic, so it shouldn't be offered.

export function bboxIntersects(a, b) {
  if (!a || !b || a.length < 4 || b.length < 4) return false;
  return a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
}

// True when `outer` fully contains `inner` (scene footprint covers the AOI).
export function bboxContains(outer, inner) {
  if (!outer || !inner || outer.length < 4 || inner.length < 4) return false;
  return (
    outer[0] <= inner[0] &&
    outer[1] <= inner[1] &&
    outer[2] >= inner[2] &&
    outer[3] >= inner[3]
  );
}

// ── shared helpers ──────────────────────────────────────────────────────────

function absUrl(href, base) {
  return new URL(href, base).href;
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function resolvePhase(explicit, datetime, eventDate) {
  if (explicit === "pre" || explicit === "post") return explicit;
  if (!datetime || !eventDate) return null;
  return datetime.slice(0, 10) < eventDate ? "pre" : "post";
}

function bboxToGeometry(bbox) {
  if (!bbox || bbox.length < 4) return null;
  const [w, s, e, n] = bbox;
  return {
    type: "Polygon",
    coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
  };
}

function sceneSortKey(a, b) {
  const phaseRank = (p) => (p === "pre" ? 0 : 1);
  const sourceRank = (s) => (s === "Vantor" ? 0 : 1);
  return (
    phaseRank(a.phase) - phaseRank(b.phase) ||
    sourceRank(a.source) - sourceRank(b.source) ||
    (a.datetime || "").localeCompare(b.datetime || "")
  );
}

async function fetchJson(url) {
  const res = await fetch(url, { mode: "cors" });
  if (!res.ok) throw new Error(`Fetch failed (${res.status}): ${url}`);
  return res.json();
}

// Fetch JSON with small retry/backoff — STAC hosts occasionally 5xx.
async function fetchJsonRetry(url, attempts = 3) {
  for (let i = 1; i <= attempts; i++) {
    try {
      const res = await fetch(url, { mode: "cors" });
      if (res.ok) return { doc: await res.json(), url: res.url || url };
      if (res.status < 500 || i === attempts) {
        throw new Error(`Fetch failed (${res.status}): ${url}`);
      }
    } catch (err) {
      if (i === attempts) throw err;
    }
    await delay(250 * i);
  }
  throw new Error(`Fetch failed: ${url}`);
}

function stacLink(doc, rel, base) {
  const link = (doc.links || []).find((l) => l.rel === rel && l.href);
  return link ? absUrl(link.href, base) : null;
}

function stacLinks(doc, rel) {
  return (doc.links || []).filter((l) => l.rel === rel && l.href);
}

function assetHref(asset, base) {
  return asset && asset.href ? absUrl(asset.href, base) : null;
}

function isGeotiffAsset(asset) {
  return (
    ((asset && asset.type) || "").includes("geotiff") ||
    /\.tiff?($|\?)/i.test((asset && asset.href) || "")
  );
}

function pickVisualAsset(assets = {}) {
  return (
    assets.visual ||
    Object.values(assets).find(
      (a) => isGeotiffAsset(a) && (a.roles || []).includes("visual")
    ) ||
    Object.values(assets).find(isGeotiffAsset) ||
    null
  );
}

function assetSize(asset) {
  const raw = asset && (asset["file:size"] || asset.size || asset.file_size);
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

// ── event discovery ─────────────────────────────────────────────────────────

const MONTHS = {
  jan: "01", feb: "02", mar: "03", apr: "04", may: "05", jun: "06",
  jul: "07", aug: "08", sep: "09", oct: "10", nov: "11", dec: "12",
};

const HAZARD_WORDS = new Set([
  "earthquake", "typhoon", "hurricane", "flood", "flooding", "ebola",
  "wildfire", "fire", "cyclone", "tornado", "landslide", "volcano",
  "eruption", "tsunami", "storm", "drought", "outbreak", "mudslide",
]);

// Turn a catalog id (e.g. "Venezuela-Earthquake-Jun-2026" or
// "venezuela-earthquake-2026-06-24") into a human label + best-effort date.
function prettifyEventName(id) {
  const words = [];
  const dateParts = [];
  for (const tok of id.split(/[-_]/).filter(Boolean)) {
    const lt = tok.toLowerCase();
    if (/^\d+$/.test(tok) || MONTHS[lt]) {
      dateParts.push(MONTHS[lt] ? tok[0].toUpperCase() + lt.slice(1) : tok);
    } else {
      words.push(tok[0].toUpperCase() + tok.slice(1));
    }
  }
  const name = words.join(" ") || id;
  return dateParts.length ? `${name} (${dateParts.join(" ")})` : name;
}

function parseDateFromId(id) {
  let m = id.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = id.toLowerCase().match(/([a-z]{3,})-(\d{4})/);
  if (m && MONTHS[m[1].slice(0, 3)]) return `${m[2]}-${MONTHS[m[1].slice(0, 3)]}-15`;
  m = id.match(/(\d{4})/);
  if (m) return `${m[1]}-01-01`;
  return null;
}

// Split an id into place vs hazard tokens (dates/numbers dropped) so events
// from different catalogs can be matched (e.g. Vantor "Venezuela-Earthquake-
// Jun-2026" ↔ Planet "venezuela-earthquake-2026-06-24").
function eventTokens(id) {
  const toks = id
    .toLowerCase()
    .split(/[-_]/)
    .filter((t) => t.length > 1 && !/^\d+$/.test(t) && !(t in MONTHS));
  const place = new Set(toks.filter((t) => !HAZARD_WORDS.has(t)));
  const hazard = new Set(toks.filter((t) => HAZARD_WORDS.has(t)));
  return { place, hazard };
}

function eventsMatch(idA, idB) {
  const a = eventTokens(idA);
  const b = eventTokens(idB);
  const placeOverlap = [...a.place].some((t) => b.place.has(t));
  if (!placeOverlap) return false;
  const hazardOverlap = [...a.hazard].some((t) => b.hazard.has(t));
  return hazardOverlap || a.hazard.size === 0 || b.hazard.size === 0;
}

async function discoverVantorEvents() {
  const root = await fetchJson(VANTOR_ROOT_CATALOG);
  return stacLinks(root, "child").map((l) => {
    const href = absUrl(l.href, VANTOR_ROOT_CATALOG);
    const m = href.match(/events\/([^/]+)\/collection\.json/);
    const id = m ? m[1] : href;
    return { id, collectionUrl: href, date: parseDateFromId(id) };
  });
}

async function discoverPlanetEvents() {
  const { doc: root, url } = await fetchJsonRetry(PLANET_ROOT_CATALOG);
  return stacLinks(root, "child").map((l) => {
    const catalogUrl = absUrl(l.href, url);
    const m = catalogUrl.match(/disasterdata\/([^/]+)\/catalog\.json/);
    const id = m ? m[1] : catalogUrl;
    return { id, catalogUrl, date: parseDateFromId(id) };
  });
}

/**
 * Discover every disaster event available across Vantor and Planet, merging
 * events that appear in both catalogs. Resilient: if one root catalog fails,
 * the other's events are still returned.
 *
 * @returns {Promise<{ events: Array, errors: Array<{source, message}> }>}
 *   each event: { key, name, date, sources: { vantor?, planet? } }
 */
export async function discoverEvents() {
  const errors = [];
  const [vantor, planet] = await Promise.all([
    discoverVantorEvents().catch((err) => {
      console.error("Vantor event discovery failed:", err);
      errors.push({ source: "Vantor", message: err.message });
      return [];
    }),
    discoverPlanetEvents().catch((err) => {
      console.error("Planet event discovery failed:", err);
      errors.push({ source: "Planet", message: err.message });
      return [];
    }),
  ]);

  const events = [];
  const planetUsed = new Set();
  for (const v of vantor) {
    const match = planet.find(
      (p) => !planetUsed.has(p.id) && eventsMatch(v.id, p.id)
    );
    if (match) planetUsed.add(match.id);
    events.push({
      key: v.id,
      name: prettifyEventName(v.id),
      date: v.date || match?.date || null,
      sources: match ? { vantor: v, planet: match } : { vantor: v },
    });
  }
  for (const p of planet) {
    if (planetUsed.has(p.id)) continue;
    events.push({
      key: p.id,
      name: prettifyEventName(p.id),
      date: p.date,
      sources: { planet: p },
    });
  }

  // Most recent first; unknown dates last.
  events.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return { events, errors };
}

// ── Vantor Open Data (STAC item links) ──────────────────────────────────────

function normalizeVantorItem(item, eventDate, itemHref = null) {
  const props = item.properties || {};
  const visual = pickVisualAsset(item.assets);
  const cogUrl = visual?.href || null;
  const thumbUrl =
    item.assets?.thumbnail?.href ||
    (cogUrl ? cogUrl.replace(/\.tif$/i, ".jpg") : null);
  return {
    id: item.id,
    source: "Vantor",
    phase: resolvePhase(props.phase, props.datetime, eventDate),
    cogUrl,
    thumbUrl,
    bbox: item.bbox,
    geometry: item.geometry || bboxToGeometry(item.bbox),
    datetime: props.datetime || null,
    title: props.title || item.id,
    place: props.location || props.location_slug || null,
    sensor: props.vehicle_name || props.platform || null,
    constellation: props.constellation || null,
    gsd: props.pan_gsd ?? props.gsd ?? null,
    cloud: props["eo:cloud_cover"] ?? null,
    offNadir: props["view:off_nadir"] ?? null,
    sunElev: props["view:sun_elevation"] ?? null,
    cogSize: assetSize(visual),
    sourceUrl: cogUrl,
    // STAC item URL we fetched — the derived_from provenance target.
    itemHref: itemHref || null,
    sourceTypeKey: SOURCE_TYPE_KEYS.vantor,
  };
}

// Fetch + normalize the STAC items linked directly from a Vantor collection
// document located at `baseUrl`.
async function fetchVantorItems(doc, baseUrl, eventDate) {
  const itemLinks = stacLinks(doc, "item");
  const scenes = await Promise.all(
    itemLinks.map(async (l) => {
      try {
        const itemUrl = absUrl(l.href, baseUrl);
        const item = await fetchJson(itemUrl);
        return normalizeVantorItem(item, eventDate, itemUrl);
      } catch {
        return null;
      }
    })
  );
  return scenes.filter(Boolean);
}

// Vantor events normally list every scene item directly under the event
// collection. As a safety net for a future event that instead nests items
// under child collections (as some Planet events do — see
// collectPlanetCollections), descend child links *only when a collection
// exposes no direct items*. Events that already list items flat — the current
// norm, including ones that ALSO nest redundant pre/post children — keep their
// existing behavior with no extra fetches and no duplicate scenes.
const VANTOR_MAX_DEPTH = 5;

async function collectVantorScenes(doc, baseUrl, eventDate, depth = 0) {
  const direct = await fetchVantorItems(doc, baseUrl, eventDate);
  if (direct.length > 0 || depth >= VANTOR_MAX_DEPTH) return direct;
  const childLinks = stacLinks(doc, "child");
  const nested = await Promise.all(
    childLinks.map(async (link) => {
      const childUrl = absUrl(link.href, baseUrl);
      try {
        const childDoc = await fetchJson(childUrl);
        return collectVantorScenes(childDoc, childUrl, eventDate, depth + 1);
      } catch (err) {
        console.warn(`Skipping Vantor STAC catalog ${childUrl}: ${err.message}`);
        return [];
      }
    })
  );
  return nested.flat();
}

async function fetchVantorScenes(src) {
  const collection = await fetchJson(src.collectionUrl);
  const eventDate = (collection["odp:event_date"] || "").slice(0, 10) || null;
  return collectVantorScenes(collection, src.collectionUrl, eventDate);
}

// ── Planet Open Data (Source Cooperative STAC) ──────────────────────────────

function planetPhaseFromCollectionId(id) {
  if (id === "pre-event") return "pre";
  if (id === "post-event") return "post";
  return null;
}

function planetSourceTypeKey(item, collection) {
  const itemType =
    item?.properties?.["pl:item_type"] || collection?.title || "";
  return /skysat/i.test(itemType)
    ? SOURCE_TYPE_KEYS.planetSkysat
    : SOURCE_TYPE_KEYS.planet;
}

function normalizePlanetItem({
  item,
  itemUrl,
  collection,
  collectionUrl,
  aboutUrl,
  eventDate,
  inheritedPhase,
}) {
  const props = item.properties || {};
  const visual = pickVisualAsset(item.assets);
  const cogUrl = visual ? absUrl(visual.href, itemUrl) : null;
  // Prefer a per-item thumbnail; otherwise fall back to the collection's
  // shared thumbnail. The collection asset's href is relative to the
  // collection document, not the item — resolve it against collectionUrl
  // (some events, e.g. Gironde, ship no per-item thumbnail, so this fallback
  // is the only list preview they have).
  const thumbUrl =
    assetHref(item.assets?.thumbnail, itemUrl) ||
    assetHref(collection?.assets?.thumbnail, collectionUrl || itemUrl);
  const phase =
    planetPhaseFromCollectionId(item.collection || collection?.id) ||
    inheritedPhase ||
    resolvePhase(null, props.datetime, eventDate);
  return {
    id: item.id,
    source: "Planet",
    phase,
    cogUrl,
    thumbUrl,
    bbox: item.bbox,
    geometry: item.geometry || bboxToGeometry(item.bbox),
    datetime: props.datetime || props.start_datetime || props.end_datetime || null,
    title: props.title || item.title || item.id,
    place: props.location || props.location_slug || collection?.title || null,
    sensor: props.platform || props["pl:item_type"] || props.constellation || null,
    constellation: props.constellation || "planet",
    gsd: props.gsd ?? collection?.summaries?.gsd?.[0] ?? null,
    cloud: props["eo:cloud_cover"] ?? null,
    offNadir: props["view:off_nadir"] ?? null,
    sunElev: props["view:sun_elevation"] ?? null,
    cogSize: assetSize(visual),
    sourceUrl: cogUrl || aboutUrl,
    // STAC item URL we fetched — the derived_from provenance target.
    itemHref: itemUrl || null,
    sourceTypeKey: planetSourceTypeKey(item, collection),
  };
}

// Some Planet collections expose a single pre-event mosaic asset instead of
// per-scene items.
function normalizePlanetMosaic({ collection, collectionUrl, asset }) {
  const cogUrl = absUrl(asset.href, collectionUrl);
  const [start] = collection.extent?.temporal?.interval?.[0] || [];
  return {
    id: `planet-${collection.id}-mosaic`,
    source: "Planet",
    phase: planetPhaseFromCollectionId(collection.id) || "pre",
    cogUrl,
    thumbUrl: assetHref(collection.assets?.thumbnail, collectionUrl) || null,
    bbox: collection.extent?.spatial?.bbox?.[0] || null,
    geometry: bboxToGeometry(collection.extent?.spatial?.bbox?.[0]),
    datetime: start || null,
    title: asset.title || collection.title || collection.id,
    place: collection.title || null,
    sensor: "Planet Basemap",
    constellation: "planet",
    gsd: collection.summaries?.gsd?.[0] ?? null,
    cloud: null,
    offNadir: null,
    sunElev: null,
    cogSize: assetSize(asset),
    sourceUrl: cogUrl,
    // No per-item STAC record for a mosaic; reference the collection document.
    itemHref: collectionUrl || null,
    sourceTypeKey: SOURCE_TYPE_KEYS.planet,
  };
}

async function fetchPlanetCollectionScenes({
  collectionDoc,
  collectionUrl,
  aboutUrl,
  eventDate,
  inheritedPhase,
}) {
  const phase = planetPhaseFromCollectionId(collectionDoc.id) || inheritedPhase;
  const mosaic = phase === "pre" ? collectionDoc.assets?.mosaic : null;
  if (mosaic) {
    return [
      normalizePlanetMosaic({
        collection: collectionDoc,
        collectionUrl,
        asset: mosaic,
      }),
    ];
  }
  const itemLinks = stacLinks(collectionDoc, "item");
  const items = await Promise.all(
    itemLinks.map(async (link) => {
      const itemUrl = absUrl(link.href, collectionUrl);
      try {
        const { doc, url } = await fetchJsonRetry(itemUrl);
        return normalizePlanetItem({
          item: doc,
          itemUrl: url,
          collection: collectionDoc,
          collectionUrl,
          aboutUrl,
          eventDate,
          inheritedPhase: phase,
        });
      } catch (err) {
        console.warn(`Skipping Planet STAC item ${itemUrl}: ${err.message}`);
        return null;
      }
    })
  );
  return items.filter(Boolean);
}

// Recursively descend Planet STAC `child` links until reaching nodes that
// actually hold scenes (item links or a pre-event mosaic asset). Most events
// expose collections directly under the root, but some nest an extra catalog
// level (root → pre-/post-event catalog → dated collections → items); without
// this walk those events surface as "no imagery available". The pre/post
// `phase` is carried down from whichever ancestor declares it (e.g. the
// intermediate "post-event" catalog), since the leaf collection ids
// ("post-event-2026-07-29") don't match on their own.
const PLANET_MAX_DEPTH = 5;

async function collectPlanetCollections(doc, url, aboutUrl, inheritedPhase, depth = 0) {
  const phase = planetPhaseFromCollectionId(doc.id) || inheritedPhase;
  const about = stacLink(doc, "about", url) || aboutUrl;
  const hasItems = stacLinks(doc, "item").length > 0;
  const hasMosaic = phase === "pre" && !!doc.assets?.mosaic;
  if (hasItems || hasMosaic) {
    return [{ doc, url, aboutUrl: about, phase }];
  }
  if (depth >= PLANET_MAX_DEPTH) return [];
  const childLinks = stacLinks(doc, "child");
  const nested = await Promise.all(
    childLinks.map(async (link) => {
      const childUrl = absUrl(link.href, url);
      try {
        const { doc: childDoc, url: resolvedUrl } = await fetchJsonRetry(childUrl);
        return collectPlanetCollections(childDoc, resolvedUrl, about, phase, depth + 1);
      } catch (err) {
        console.warn(`Skipping Planet STAC catalog ${childUrl}: ${err.message}`);
        return [];
      }
    })
  );
  return nested.flat();
}

async function fetchPlanetScenes(src) {
  const { doc: root, url: rootUrl } = await fetchJsonRetry(src.catalogUrl);
  const rootAbout = stacLink(root, "about", rootUrl);
  const collections = await collectPlanetCollections(root, rootUrl, rootAbout, null);
  const nested = await Promise.all(
    collections.map(({ doc, url, aboutUrl, phase }) =>
      fetchPlanetCollectionScenes({
        collectionDoc: doc,
        collectionUrl: url,
        aboutUrl,
        eventDate: src.date,
        inheritedPhase: phase,
      })
    )
  );
  return nested.flat().filter(Boolean);
}

// ── public API ──────────────────────────────────────────────────────────────

/**
 * Fetch and normalize the full catalog for a discovered event, pulling from
 * whichever sources the event has. Resilient per-source: a failing source is
 * dropped with a console warning and reported in `errors` rather than failing
 * the whole catalog.
 *
 * @param {object} event a value from discoverEvents().events
 * @returns {Promise<{ scenes: Array, errors: Array<{source, message}> }>}
 */
export async function fetchEventCatalog(event) {
  const errors = [];
  const vantorTask = event.sources?.vantor
    ? fetchVantorScenes(event.sources.vantor).catch((err) => {
        console.error("Vantor load failed:", err);
        errors.push({ source: "Vantor", message: err.message });
        return [];
      })
    : Promise.resolve([]);
  const planetTask = event.sources?.planet
    ? fetchPlanetScenes(event.sources.planet).catch((err) => {
        console.error("Planet load failed:", err);
        errors.push({ source: "Planet", message: err.message });
        return [];
      })
    : Promise.resolve([]);

  const [vantor, planet] = await Promise.all([vantorTask, planetTask]);
  const scenes = dedupeScenes([...vantor, ...planet]).sort(sceneSortKey);
  // Guaranteed-unique identity for React keys / map feature ids, even if two
  // scenes still share a STAC id after dedupe.
  scenes.forEach((s, i) => {
    s.uid = `${s.source}:${s.id}:${i}`;
  });
  return { scenes, errors };
}

// Some source catalogs contain duplicate STAC ids (same scene listed twice).
// Collapse them by source + COG URL (falling back to id) so downstream React
// keys and map feature ids stay unique.
function dedupeScenes(scenes) {
  const seen = new Set();
  const out = [];
  for (const s of scenes) {
    const key = `${s.source}|${s.cogUrl || s.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}
