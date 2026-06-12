import { useState } from "react";
import { AlertModal } from "../AlertModal";

interface NumberFieldProps {
  /** Committed numeric value (the parent's source of truth). */
  value: number;
  /** Shown as a grey placeholder and used as the reset target on invalid input. */
  defaultValue: number;
  min: number;
  max: number;
  onCommit: (n: number) => void;
  /** Noun used in the alert message, e.g. "Copies". */
  label: string;
  /** Optional unit appended to the alert message, e.g. "seconds". */
  unit?: string;
  ariaLabel?: string;
  style?: React.CSSProperties;
}

// A whole-number input that defers validation to blur instead of correcting on
// every keystroke. While focused the user may type anything; on blur an empty
// box falls back to the default (grey), a valid value commits, and an invalid
// one (non-numeric or out of range) pops an AlertModal and resets to default.
//
// The displayed text is internal draft state, so external changes to `value`
// (e.g. the import reset for Copies) require remounting via a React `key`.
export function NumberField({
  value,
  defaultValue,
  min,
  max,
  onCommit,
  label,
  unit,
  ariaLabel,
  style,
}: NumberFieldProps) {
  // Empty string renders the grey placeholder; a value equal to the default
  // also starts empty so the default reads as "not overridden".
  const [draft, setDraft] = useState<string>(value === defaultValue ? "" : String(value));
  const [error, setError] = useState<string | null>(null);

  const expectation = `${label} must be a whole number from ${min} to ${max}${unit ? ` ${unit}` : ""}.`;

  const reject = () => {
    setError(expectation);
    setDraft("");
    onCommit(defaultValue);
  };

  const handleBlur = () => {
    const text = draft.trim();
    if (text === "") {
      setDraft("");
      onCommit(defaultValue);
      return;
    }
    const parsed = Number(text);
    if (Number.isNaN(parsed)) {
      reject();
      return;
    }
    const rounded = Math.round(parsed);
    if (rounded < min || rounded > max) {
      reject();
      return;
    }
    setDraft(String(rounded));
    onCommit(rounded);
  };

  return (
    <>
      <input
        type="text"
        inputMode="numeric"
        aria-label={ariaLabel ?? label}
        value={draft}
        placeholder={String(defaultValue)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleBlur}
        style={style}
      />
      {error !== null && <AlertModal message={error} onClose={() => setError(null)} />}
    </>
  );
}
