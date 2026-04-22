// -----------------------------------------------------------------------------
// splitShape.jsx — ULTRA PRECISE FINE CUT WITH CLIPPER (WORKS WITH FREEHAND)
// -----------------------------------------------------------------------------
// Includes internal scaling to allow buffers of just 2–3 cm.
// -----------------------------------------------------------------------------

import ClipperLib from "clipper-lib";

// -----------------------------------------------------------------------------
//// MERCATOR HELPERS
// -----------------------------------------------------------------------------
function lonLatToMercator([lon, lat]) {
    const x = lon * 20037508.34 / 180;
    let y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180);
    y = y * 20037508.34 / 180;
    return [x, y];
}

function mercatorToLonLat([x, y]) {
    const lon = (x / 20037508.34) * 180;
    let lat = (y / 20037508.34) * 180;
    lat = (180 / Math.PI) * (2 * Math.atan(Math.exp(lat * Math.PI / 180)) - Math.PI / 2);
    return [lon, lat];
}

// -----------------------------------------------------------------------------
// SCALING TO ALLOW ULTRA-SMALL BUFFERS
// -----------------------------------------------------------------------------
const SCALE = 1000;

function scaleUp(path) {
    return path.map(p => ({ X: p.X * SCALE, Y: p.Y * SCALE }));
}

function scaleDown(path) {
    return path.map(p => ({ X: p.X / SCALE, Y: p.Y / SCALE }));
}

// -----------------------------------------------------------------------------
// CONVERT FORMAT LL → Clipper
// -----------------------------------------------------------------------------
function polyToClipper(polyLL) {
    return polyLL.map(([lon, lat]) => {
        const [x, y] = lonLatToMercator([lon, lat]);
        return { X: x, Y: y };
    });
}

function clipperToLL(poly) {
    return poly.map(({ X, Y }) => mercatorToLonLat([X, Y]));
}

// -----------------------------------------------------------------------------
// SUPER FINE LINE BUFFER: 3 cm REAL, thanks to scaling
// -----------------------------------------------------------------------------
function bufferLine(lineLL, widthMeters = 0.03) {
    // Convert line to Mercator
    const path = lineLL.map(([lon, lat]) => {
        const [x, y] = lonLatToMercator([lon, lat]);
        return { X: x, Y: y };
    });

    // Scale the geometry
    const scaled = scaleUp(path);

    const co = new ClipperLib.ClipperOffset();
    co.MiterLimit = 1;
    co.ArcTolerance = 0.1;

    let solution = [];
    co.AddPath(scaled, ClipperLib.JoinType.jtRound, ClipperLib.EndType.etOpenButt);

    // Apply the buffer (scaled)
    co.Execute(solution, widthMeters * SCALE);

    // Scale back to normal
    return solution.map(scaleDown);
}

// -----------------------------------------------------------------------------
// SPLIT POLYGON — fine cut without eating edges
// -----------------------------------------------------------------------------
export function splitPolygon(polygonShape, lineShape) {

    const props = polygonShape.data.properties || {};

    const polyLL = polygonShape.data.geometry.coordinates[0];
    const lineLL = lineShape.data.geometry.coordinates;

    const polyClip = [polyToClipper(polyLL)];

    // Buffer of 3 cm, fine enough but always functional
    const buffer = bufferLine(lineLL, 0.5);

    const cpr = new ClipperLib.Clipper();
    let result = new ClipperLib.Paths();

    cpr.AddPaths(polyClip, ClipperLib.PolyType.ptSubject, true);
    cpr.AddPaths(buffer, ClipperLib.PolyType.ptClip, true);

    cpr.Execute(
        ClipperLib.ClipType.ctDifference,
        result,
        ClipperLib.PolyFillType.pftNonZero,
        ClipperLib.PolyFillType.pftNonZero
    );

    if (!result || result.length < 2) {
        return null;
    }

    // Convert results to lat/lon
    return result.map(poly => ({
        type: "Feature",
        geometry: {
            type: "Polygon",
            coordinates: [ closeRing( clipperToLL(poly) ) ]
        },
        properties: props
    }));
}

function closeRing(coords) {
    const first = coords[0];
    const last = coords[coords.length - 1];

    // If the polygon is not closed, close it
    if (first[0] !== last[0] || first[1] !== last[1]) {
        coords.push([...first]);
    }
    return coords;
}

// -----------------------------------------------------------------------------
// ITERATE THROUGH ALL SHAPES AND CUT THOSE THAT CORRESPOND
// -----------------------------------------------------------------------------
export function splitShape(drawingManager, lineShape) {

    if (!lineShape || lineShape.data.geometry.type !== "LineString") {
        console.warn("You must draw a line to cut.");
        return;
    }

    const source = drawingManager.getSource();
    const shapes = source.getShapes();

    // Filter only polygons
    const polygons = shapes.filter(s => s.data.geometry.type === "Polygon");

    if (polygons.length === 0) {
        console.warn("There are no polygons on the map.");
        return null;
    }

    let piezasFinales = [];

    polygons.forEach(polygon => {
        const pieces = splitPolygon(polygon, lineShape);

        if (!pieces || pieces.length < 2) {
            return; // This polygon was not cut
        }

        // Remove original
        source.remove(polygon);

        const originalProps = polygon.data.properties || {};

        // Add the pieces
        pieces.forEach(p => {
            p.properties = {
                ...originalProps,
                ...p.properties
            };
            source.add(p);
        });

        piezasFinales.push(...pieces);
    });

    // Remove cut line
    source.remove(lineShape);

    if (piezasFinales.length === 0) {
        console.warn("The line did not cut any polygon.");
        return null;
    }

    return piezasFinales;
}

// -----------------------------------------------------------------------------
// UTILITIES FOR CORRECT RING ORIENTATION
// -----------------------------------------------------------------------------
function polygonArea(coords) {
    let sum = 0;
    for (let i = 0; i < coords.length - 1; i++) {
        const [x1, y1] = coords[i];
        const [x2, y2] = coords[i + 1];
        sum += (x1 * y2 - x2 * y1);
    }
    return sum / 2;
}

function ensureCCW(coords) {
    if (polygonArea(coords) < 0) {
        return coords.slice().reverse();
    }
    return coords;
}
