import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QualityPanel } from "./QualityPanel";

describe("QualityPanel", () => {
  afterEach(() => cleanup());

  it("renders Fast, Better and Best radios", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/Fast/i)).toBeTruthy();
    expect(screen.getByLabelText(/Better/i)).toBeTruthy();
    expect(screen.getByLabelText(/Best/i)).toBeTruthy();
  });

  it("checks the active quality only", () => {
    render(<QualityPanel quality="best" onChange={() => {}} />);
    expect((screen.getByLabelText(/Best/i) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/Fast/i) as HTMLInputElement).checked).toBe(false);
  });

  it("calls onChange with the clicked value", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Better/i));
    expect(onChange).toHaveBeenCalledWith("better");
  });

  it("shows no time estimate (total time is not predictable)", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.queryByText(/min/i)).toBeNull();
    expect(screen.queryByText(/\d+\s*(min|sec|s)\b/i)).toBeNull();
  });

  it("renders the Ultra radio", () => {
    render(<QualityPanel quality="fast" onChange={() => {}} />);
    expect(screen.getByLabelText(/Ultra/i)).toBeTruthy();
  });

  it("calls onChange with 'ultra' when Ultra clicked", () => {
    const onChange = vi.fn();
    render(<QualityPanel quality="fast" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Ultra/i));
    expect(onChange).toHaveBeenCalledWith("ultra");
  });
});
