import { type Ms, parseMs } from "@lirisync/core";

const SECONDS_TEXT = /^(\d+)(?:\.(\d+))?$/;

/**
 * Converts a non-negative decimal seconds string (Audacity writes six decimal
 * places) to `Ms`, rounding half up to the millisecond.
 *
 * Digits are read as integers so that no float seconds value is ever formed:
 * `Number("4.1") * 1000` happens to work, but the rounding step is where float
 * error shows up, so it is done on the digit string instead.
 */
export function parseSecondsText(text: string): Ms {
  const match = SECONDS_TEXT.exec(text);
  if (match === null) {
    throw new Error(
      `Expected non-negative decimal seconds, got ${JSON.stringify(text)}`,
    );
  }
  const whole = Number(match[1]);
  const fraction = (match[2] ?? "").padEnd(4, "0");
  const millis = Number(fraction.slice(0, 3));
  const roundUp = fraction.charAt(3) >= "5" ? 1 : 0;
  return parseMs(whole * 1000 + millis + roundUp);
}
