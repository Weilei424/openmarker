import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { AlertModal } from "./AlertModal";

describe("AlertModal", () => {
  afterEach(() => cleanup());

  it("renders the message and an OK button", () => {
    render(<AlertModal message="Copies must be a whole number from 1 to 20." onClose={() => {}} />);
    expect(screen.getByText(/Copies must be a whole number from 1 to 20\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: /ok/i })).toBeTruthy();
  });

  it("exposes an alertdialog role for accessibility", () => {
    render(<AlertModal message="Bad value." onClose={() => {}} />);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("calls onClose when OK is clicked", () => {
    const onClose = vi.fn();
    render(<AlertModal message="Bad value." onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /ok/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<AlertModal message="Bad value." onClose={onClose} />);
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
