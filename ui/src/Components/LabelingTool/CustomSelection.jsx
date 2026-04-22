import { useEffect, useRef, useState } from "react";
import atlas from "azure-maps-control";

export default function PolygonMultiEdit({ map, polygonCoords, onChange }) {
    const [selected, setSelected] = useState([]);
    const markersRef = useRef([]);

    useEffect(() => {
        if (!map || !polygonCoords) return;

        markersRef.current.forEach(m => map.markers.remove(m));
        markersRef.current = [];

        polygonCoords.forEach((coord, index) => {
            const marker = new atlas.HtmlMarker({
                position: coord,
                htmlContent: `
                    <div class="custom-vertex" data-index="${index}"></div>
                `,
                pixelOffset: [0, 0]
            });

            map.markers.add(marker);

            marker._index = index;

            marker.getOptions().htmlContent.addEventListener("mousedown", (e) => {
                handleVertexMouseDown(e, index, coord);
            });

            markersRef.current.push(marker);
        });

    }, [map, polygonCoords, selected]);

    function handleVertexMouseDown(e, index) {
        e.stopPropagation();

        const multi = e.shiftKey || e.ctrlKey;

        setSelected(prev => {
            if (multi) {
                if (prev.includes(index)) return prev;
                return [...prev, index];
            } else {
                return [index];
            }
        });

        startDragging(index);
    }

    function startDragging(index) {
        let lastPos = null;

        function onMove(evt) {
            const pos = map.pixelsToPositions([evt.pixelX, evt.pixelY])[0];
            if (!lastPos) {
                lastPos = pos;
                return;
            }

            const dx = pos[0] - lastPos[0];
            const dy = pos[1] - lastPos[1];
            lastPos = pos;

            const newCoords = polygonCoords.map((p, i) =>
                selected.includes(i)
                    ? [p[0] + dx, p[1] + dy]
                    : p
            );

            onChange(newCoords);
        }

        function onUp() {
            map.events.remove("mousemove", onMove);
            map.events.remove("mouseup", onUp);
        }

        map.events.add("mousemove", onMove);
        map.events.add("mouseup", onUp);
    }

    return null;
}
