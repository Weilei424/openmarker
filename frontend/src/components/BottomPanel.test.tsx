import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BottomPanel, formatDuration } from "./BottomPanel";

describe("formatDuration", () => {
  it("formats 0 ms as 00:00", () => {
    expect(formatDuration(0)).toBe("00:00");
  });
  it("formats 3500 ms as 00:03", () => {
    expect(formatDuration(3500)).toBe("00:03");
  });
  it("formats 125000 ms as 02:05", () => {
    expect(formatDuration(125000)).toBe("02:05");
  });
  it("formats 1 hour as 60:00", () => {
    expect(formatDuration(3_600_000)).toBe("60:00");
  });
});

describe("BottomPanel", () => {
  it("shows length, utilization and duration when given an entry", () => {
    render(
      <BottomPanel
        markerLengthMm={1234.5}
        utilizationPct={82.4}
        durationMs={3500}
      />
    );
    expect(screen.getByText(/1235 mm/)).toBeTruthy();
    expect(screen.getByText(/82\.4%/)).toBeTruthy();
    expect(screen.getByText(/00:03/)).toBeTruthy();
  });

  it("renders an empty placeholder when no entry data is provided", () => {
    render(<BottomPanel markerLengthMm={null} utilizationPct={null} durationMs={null} />);
    expect(screen.getByText(/no layout yet/i)).toBeTruthy();
  });
});
