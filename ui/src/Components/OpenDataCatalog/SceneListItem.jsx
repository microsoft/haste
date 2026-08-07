// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import {
  Button,
  Link,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import { SOURCE_COLORS } from "./openDataCatalog";

const useStyles = makeStyles({
  item: {
    display: "flex",
    alignItems: "flex-start",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingVerticalS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    cursor: "pointer",
    color: tokens.colorNeutralForeground1,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  selected: {
    backgroundColor: tokens.colorBrandBackground2,
    ":hover": {
      backgroundColor: tokens.colorBrandBackground2Hover,
    },
  },
  hovered: {
    backgroundColor: tokens.colorNeutralBackground1Hover,
  },
  thumbnail: {
    width: "56px",
    height: "56px",
    flexShrink: 0,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground3,
    backgroundPosition: "center",
    backgroundSize: "cover",
    backgroundRepeat: "no-repeat",
    display: "grid",
    placeItems: "center",
  },
  secondaryText: {
    color: tokens.colorNeutralForeground2,
  },
  metadata: {
    borderTop: `${tokens.strokeWidthThin} dashed ${tokens.colorNeutralStroke2}`,
  },
  metadataValue: {
    paddingRight: tokens.spacingHorizontalL,
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
  },
  errorText: {
    color: tokens.colorStatusDangerForeground1,
    marginTop: tokens.spacingVerticalXXS,
  },
});

function formatDate(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").replace(/\.\d+Z?$/, "").replace("Z", "").slice(0, 16) + " UTC";
}

function formatGsd(gsd) {
  const n = Number(gsd);
  if (gsd == null || gsd === "" || !Number.isFinite(n)) return null;
  return `${n.toFixed(2)} m GSD`;
}

function formatSize(bytes) {
  // Treat only null/undefined/"" as absent so a legitimate 0-byte asset
  // still formats as "0 B" (rather than being hidden by a falsy check).
  if (bytes == null || bytes === "") return null;
  let n = Number(bytes);
  if (!Number.isFinite(n)) return null;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

const Badge = ({ label, color, filled }) => (
  <span
    className="me-1"
    style={{
      display: "inline-block",
      fontSize: "10px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.04em",
      borderRadius: "999px",
      padding: "1px 8px",
      color: filled ? "#fff" : color,
      background: filled ? color : `${color}1a`,
      border: `1px solid ${color}59`,
    }}
  >
    {label}
  </span>
);
Badge.propTypes = {
  label: PropTypes.string.isRequired,
  color: PropTypes.string.isRequired,
  filled: PropTypes.bool,
};

// Extra metadata shown only when a scene is selected. Rows with no value
// are omitted so the panel stays compact.
function ExpandedMeta({ scene, styles }) {
  const rows = [
    ["Captured", formatDate(scene.datetime)],
    [
      "Sensor",
      [scene.sensor, scene.constellation].filter(Boolean).join(" · ") || null,
    ],
    ["GSD", formatGsd(scene.gsd)],
    ["Cloud", scene.cloud == null ? null : `${scene.cloud}%`],
    [
      "Off-nadir",
      scene.offNadir == null ? null : `${Number(scene.offNadir).toFixed(1)}°`,
    ],
    [
      "Sun elev.",
      scene.sunElev == null ? null : `${Number(scene.sunElev).toFixed(1)}°`,
    ],
    ["Size", formatSize(scene.cogSize)],
  ].filter(([, v]) => v != null && v !== "" && v !== "—");

  return (
    <div
      className={`mt-2 pt-2 ${styles.metadata}`}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "2px 10px",
          fontSize: 11.5,
        }}
      >
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <span className={styles.secondaryText}>{k}</span>
            <span className={styles.metadataValue}>
              {v}
            </span>
          </div>
        ))}
      </div>
      {scene.sourceUrl && (
        <Link
          href={scene.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 11.5 }}
          className="d-inline-block mt-1"
        >
          ↗ View source
        </Link>
      )}
    </div>
  );
}
ExpandedMeta.propTypes = {
  scene: PropTypes.object.isRequired,
  styles: PropTypes.object.isRequired,
};

const SceneListItem = ({
  scene,
  isHovered,
  isSelected,
  onHover,
  onSelect,
  onAdd,
  addedPre,
  addedPost,
  coversAoi,
  disabled,
}) => {
  const styles = useStyles();
  const color = SOURCE_COLORS[scene.source] || "#616161";
  const gsd = formatGsd(scene.gsd);
  const hasCog = !!scene.cogUrl;

  // A scene can only be added to its own phase — pre imagery to Pre, post to
  // Post. When the phase is unknown, offer both as a fallback.
  const showPre = scene.phase === "pre" || !scene.phase;
  const showPost = scene.phase === "post" || !scene.phase;

  return (
    <div
      data-scene-uid={scene.uid || scene.id}
      className={`${styles.item} ${isSelected ? styles.selected : ""} ${
        isHovered ? styles.hovered : ""
      }`}
      style={{
        borderLeft: isSelected ? `3px solid ${color}` : "3px solid transparent",
      }}
      onMouseEnter={() => onHover(scene.uid || scene.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onSelect(scene)}
    >
      <div
        className={styles.thumbnail}
        style={{
          backgroundImage: scene.thumbUrl ? `url("${scene.thumbUrl}")` : "none",
        }}
      >
        {!scene.thumbUrl && (
          <FluentIcon name="Image" style={{ color, fontSize: 20 }} />
        )}
      </div>

      <div className="flex-grow-1" style={{ minWidth: 0 }}>
        <div className="mb-1">
          <Badge label={scene.source} color={color} filled />
          {scene.phase && (
            <Badge
              label={scene.phase}
              color={scene.phase === "pre" ? "#0078d4" : "#d83b01"}
            />
          )}
          {coversAoi && <Badge label="covers AOI" color="#107c10" />}
        </div>
        <Text
          block
          truncate
          size={300}
          style={{ fontWeight: 600 }}
          title={scene.place || scene.title || scene.id}
        >
          {scene.place || scene.title || scene.id}
        </Text>
        <Text block size={200} className={styles.secondaryText}>
          {formatDate(scene.datetime)}
          {scene.sensor ? ` · ${scene.sensor}` : ""}
          {gsd ? ` · ${gsd}` : ""}
        </Text>

        <div className="d-flex mt-2" style={{ gap: "6px" }} onClick={(e) => e.stopPropagation()}>
          {showPre && (
            <Button
              size="small"
              appearance={!addedPre && hasCog && scene.phase === "pre" ? "primary" : "secondary"}
              disabled={disabled || !hasCog || addedPre}
              onClick={() => onAdd(scene, "preEventImageryUrls")}
            >
              {addedPre ? "Added to Pre" : "+ Pre-event"}
            </Button>
          )}
          {showPost && (
            <Button
              size="small"
              appearance={!addedPost && hasCog && scene.phase !== "pre" ? "primary" : "secondary"}
              disabled={disabled || !hasCog || addedPost}
              onClick={() => onAdd(scene, "postEventImageryUrls")}
            >
              {addedPost ? "Added to Post" : "+ Post-event"}
            </Button>
          )}
        </div>
        {!hasCog && (
          <Text block size={200} className={styles.errorText}>
            COG not linked yet — footprint only.
          </Text>
        )}

        {isSelected && <ExpandedMeta scene={scene} styles={styles} />}
      </div>
    </div>
  );
};

SceneListItem.propTypes = {
  scene: PropTypes.object.isRequired,
  isHovered: PropTypes.bool,
  isSelected: PropTypes.bool,
  onHover: PropTypes.func.isRequired,
  onSelect: PropTypes.func.isRequired,
  onAdd: PropTypes.func.isRequired,
  addedPre: PropTypes.bool,
  addedPost: PropTypes.bool,
  coversAoi: PropTypes.bool,
  disabled: PropTypes.bool,
};

export default SceneListItem;
