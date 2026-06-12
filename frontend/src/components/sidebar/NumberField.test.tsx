import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { NumberField } from "./NumberField";

function setup(overrides: Partial<React.ComponentProps<typeof NumberField>> = {}) {
  const onCommit = vi.fn();
  render(
    <NumberField
      ariaLabel="copies"
      label="Copies"
      value={1}
      defaultValue={1}
      min={1}
      max={20}
      onCommit={onCommit}
      {...overrides}
    />
  );
  const input = screen.getByLabelText(/copies/i) as HTMLInputElement;
  return { input, onCommit };
}

describe("NumberField", () => {
  afterEach(() => cleanup());

  it("starts empty with the default shown as a placeholder", () => {
    const { input } = setup();
    expect(input.value).toBe("");
    expect(input.placeholder).toBe("1");
  });

  it("shows a committed non-default value as the text", () => {
    const { input } = setup({ value: 12 });
    expect(input.value).toBe("12");
  });

  it("lets the user type an out-of-range value without auto-correcting or committing", () => {
    const { input, onCommit } = setup();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "99" } });
    expect(input.value).toBe("99");
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("commits a valid in-range value on blur", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "10" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(10);
    expect(input.value).toBe("10");
  });

  it("rounds a decimal to the nearest whole number on a valid blur", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "8.6" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(9);
  });

  it("treats an empty blur as the default with no alert", () => {
    const { input, onCommit } = setup({ value: 5 });
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("alerts and resets to default when blurred out of range", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "99" } });
    fireEvent.blur(input);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toMatch(/1 to 20/);
    expect(onCommit).toHaveBeenCalledWith(1);
    expect(input.value).toBe("");
  });

  it("alerts and resets to default when blurred with a non-numeric value", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(onCommit).toHaveBeenCalledWith(1);
    expect(input.value).toBe("");
  });

  it("includes the unit in the alert message when provided", () => {
    const onCommit = vi.fn();
    render(
      <NumberField
        ariaLabel="time budget"
        label="Time budget"
        unit="seconds"
        value={600}
        defaultValue={600}
        min={360}
        max={1500}
        onCommit={onCommit}
      />
    );
    const input = screen.getByLabelText(/time budget/i);
    fireEvent.change(input, { target: { value: "100" } });
    fireEvent.blur(input);
    expect(screen.getByRole("alertdialog").textContent).toMatch(/360 to 1500 seconds/);
  });

  it("dismisses the alert when OK is clicked", () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.blur(input);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /ok/i }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
