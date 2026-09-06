// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { makeStyles, tokens } from "@fluentui/react-components";
import { CLASS_LABELS, PREDICTION_CLASSES } from "./predictionClassify.js";

const useStyles = makeStyles({
  legend: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS },
  item: {
    display: "flex", alignItems: "center", gap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground1, fontSize: tokens.fontSizeBase200,
  },
  swatch: {
    width: "28px", height: "18px", flexShrink: 0,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusSmall,
  },
  Damaged: { backgroundColor: tokens.colorStatusDangerBackground3 },
  NotDamaged: { backgroundColor: tokens.colorStatusSuccessBackground3 },
  Unknown: { backgroundColor: tokens.colorNeutralForeground3 },
});

export default function PredictionLegend() {
  const styles = useStyles();
  return (
    <div className={styles.legend} aria-label="Predicted building legend">
      {PREDICTION_CLASSES.map((cls) => (
        <div key={cls} className={styles.item}>
          <span className={`${styles.swatch} ${styles[cls]}`} aria-hidden="true" />
          <span>{CLASS_LABELS[cls]}</span>
        </div>
      ))}
    </div>
  );
}
