import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { GrainPanel } from "./GrainPanel";

describe("GrainPanel", () => {
  // No global setupFile registers @testing-library/react's auto-cleanup,
  // so do it manually — GrainPanel renders the same labels in every test
  // and would otherwise produce duplicate matches across tests.
  afterEach(() => {
    cleanup();
  });

  it("renders only single and bi radios", () => {
    render(
      <GrainPanel
        grainMode="single"
        showGrainline={true}
        onGrainModeChange={() => {}}
        onShowGrainlineChange={() => {}}
      />
    );
    expect(screen.queryByLabelText(/None/i)).toBeNull();
    expect(screen.getByLabelText(/Single direction/i)).toBeTruthy();
    expect(screen.getByLabelText(/Bi-directional/i)).toBeTruthy();
    expect(screen.queryByLabelText(/Fast mode/i)).toBeNull();
  });

  it("calls onGrainModeChange when bi clicked", () => {
    const onChange = vi.fn();
    render(
      <GrainPanel
        grainMode="single"
        showGrainline={true}
        onGrainModeChange={onChange}
        onShowGrainlineChange={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText(/Bi-directional/i));
    expect(onChange).toHaveBeenCalledWith("bi");
  });

  it("calls onShowGrainlineChange when checkbox toggled", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <GrainPanel
        grainMode="single"
        showGrainline={true}
        onGrainModeChange={() => {}}
        onShowGrainlineChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText(/Show grainline/i));
    expect(onChange).toHaveBeenLastCalledWith(false);
    onChange.mockClear();
    rerender(
      <GrainPanel
        grainMode="single"
        showGrainline={false}
        onGrainModeChange={() => {}}
        onShowGrainlineChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText(/Show grainline/i));
    expect(onChange).toHaveBeenLastCalledWith(true);
  });
});
