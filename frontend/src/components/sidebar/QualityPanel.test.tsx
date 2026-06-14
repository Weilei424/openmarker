import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QualityPanel } from "./QualityPanel";

describe("QualityPanel", () => {
  afterEach(() => cleanup());

  it("renders NFP-BLF, Genetic Algorithm quick and thorough radios", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/NFP-BLF/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*quick/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*thorough/i)).toBeTruthy();
  });

  it("checks the active quality only", () => {
    render(<QualityPanel quality="best" onChange={() => {}} />);
    expect((screen.getByLabelText(/Genetic Algorithm.*thorough/i) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/NFP-BLF/i) as HTMLInputElement).checked).toBe(false);
  });

  it("calls onChange with the clicked value", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Genetic Algorithm.*quick/i));
    expect(onChange).toHaveBeenCalledWith("better");
  });

  it("shows no per-run time prediction (only fixed algorithm budget hints)", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.queryByText(/min/i)).toBeNull();
    // 180s / 420s are fixed algorithm budget labels, not per-run predictions;
    // the test guards against variable "3 min" / "30 sec" style estimates.
    expect(screen.queryAllByText(/\d+\s*(min|sec)\b/i)).toHaveLength(0);
  });

  it("renders the Separation radio", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/Separation/i)).toBeTruthy();
  });

  it("calls onChange with 'ultra' when Ultra clicked", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Separation/i));
    expect(onChange).toHaveBeenCalledWith("ultra");
  });

  it("shows algorithm names", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/NFP-BLF/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*quick/i)).toBeTruthy();
    expect(screen.getByLabelText(/Genetic Algorithm.*thorough/i)).toBeTruthy();
    expect(screen.getByLabelText(/Separation/i)).toBeTruthy();
  });

  it("hides Separation controls unless Separation is selected", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.queryByLabelText(/time budget/i)).toBeNull();
  });

  it("shows budget + seeds controls when Separation selected", () => {
    render(<QualityPanel quality="ultra" onChange={() => {}} ultraBudgetS={600} ultraSeeds={1} />);
    expect(screen.getByLabelText(/time budget/i)).toBeTruthy();
    expect(screen.getByLabelText(/seeds/i)).toBeTruthy();
  });

  it("commits a valid time budget on blur, not while typing", () => {
    const onUltraBudgetChange = vi.fn();
    render(<QualityPanel quality="ultra" onChange={() => {}} ultraBudgetS={600}
                         onUltraBudgetChange={onUltraBudgetChange} ultraSeeds={1} />);
    const input = screen.getByLabelText(/time budget/i);
    fireEvent.change(input, { target: { value: "900" } });
    expect(onUltraBudgetChange).not.toHaveBeenCalled(); // no auto-correct mid-type
    fireEvent.blur(input);
    expect(onUltraBudgetChange).toHaveBeenCalledWith(900);
  });

  it("alerts and resets the budget to the 600s default when blurred out of range", () => {
    const onUltraBudgetChange = vi.fn();
    render(<QualityPanel quality="ultra" onChange={() => {}} ultraBudgetS={600}
                         onUltraBudgetChange={onUltraBudgetChange} ultraSeeds={1} />);
    const input = screen.getByLabelText(/time budget/i);
    fireEvent.change(input, { target: { value: "3000" } });
    fireEvent.blur(input);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(onUltraBudgetChange).toHaveBeenCalledWith(600);
  });
});
