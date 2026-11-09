import type { AnchoredLine } from "@lirisync/core";
import type { TruthLine } from "./labels";
import type { Prediction } from "./metrics";

/**
 * Confidence of an anchored line using stage 1 alone: the share of its
 * characters that matched the ASR exactly. This is a stand-in; it is expected
 * to change when stage 2 lands and the aligner reports its own confidence.
 */
export function stageOneConfidence(
  line: Extract<AnchoredLine, { status: "anchor" }>,
): number {
  return line.matchRatio;
}

/**
 * Turns stage-1 output into metric predictions. Lines are numbered from 1.
 * Unmatched and not-sung lines both count as "no start".
 */
export function toPredictions(lines: readonly AnchoredLine[]): Prediction[] {
  return lines.map((line, index): Prediction => {
    const number = index + 1;
    if (line.status === "anchor") {
      return {
        line: number,
        start: line.start,
        confidence: stageOneConfidence(line),
      };
    }
    return { line: number, start: null };
  });
}

/**
 * Throws when a labeled line is one the worker calls `not_sung` (e.g. a line
 * of symbols only). Such a line always predicts "no start", so keeping its
 * label would lower the match rate for a reason that is not the aligner's.
 * Names the 1-based lines.
 */
export function assertLabeledLinesSung(
  truth: readonly TruthLine[],
  lines: readonly AnchoredLine[],
): void {
  const offending = truth
    .filter(({ line }) => lines[line - 1]?.status === "not_sung")
    .map(({ line }) => line);
  if (offending.length > 0) {
    const noun = offending.length === 1 ? "line" : "lines";
    throw new Error(
      `Labeled but reported as not sung by the worker: ${noun} ${offending.join(", ")}`,
    );
  }
}
