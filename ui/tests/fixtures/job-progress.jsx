import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, FluentProvider, webLightTheme } from "@fluentui/react-components";
import StatusIndicator from "../../src/Components/OtherComponents/StatusIndicator";

const cases = {
  Queued: { status: "Queued", currentStep: 0, totalSteps: 2, progressPct: 0, statusMessage: "" },
  "Running without metrics": { status: "InProgress", currentStep: 0, totalSteps: 2, progressPct: null, statusMessage: "" },
  "Running with metrics": {
    status: "InProgress", currentStep: 1, totalSteps: 4, progressPct: 25,
    statusMessage: "2026-01-01T00:00:00.000000+00:00: Training in progress",
  },
  "Percentage without counters": { status: "InProgress", progressPct: 25, statusMessage: "" },
  Processed: { status: "Processed", currentStep: 0, totalSteps: 2, progressPct: 0, statusMessage: "" },
  Failed: { status: "Failed", statusMessage: "" },
  Cancelled: { status: "Cancelled", statusMessage: "" },
  Legacy: { status: "InProgress" },
};

export function Fixture() {
  const [value, setValue] = useState(cases.Queued);
  return (
    <FluentProvider theme={webLightTheme}>
      <h1>Job progress fixture</h1>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {Object.entries(cases).map(([name, props]) => (
          <Button key={name} onClick={() => setValue(props)}>{name}</Button>
        ))}
        <Button onClick={() => setValue(previous => ({ ...previous, statusMessage: "" }))}>
          Clear messages
        </Button>
      </div>
      <div data-testid="status" style={{ padding: 24 }}>
        <StatusIndicator {...value} />
      </div>
    </FluentProvider>
  );
}

createRoot(document.getElementById("root")).render(<Fixture />);
