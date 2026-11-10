import type { AnchoredLine, LineWindow, RefinedLine } from "@lirisync/core";
import type { Prediction } from "./metrics";

/** The window of each line: where stage 1 anchored it, `null` for the rest. */
export function windowsFromAnchors(
  lines: readonly AnchoredLine[],
): (LineWindow | null)[] {
  return lines.map((line) =>
    line.status === "anchor" ? { start: line.start, end: line.end } : null,
  );
}

/**
 * Confidence of a refined line: the exponential of the per-frame log
 * likelihood ratio, so 1 is a path as good as the best one and values near 0
 * are poorly supported by the audio. This is provisional; it has not been
 * calibrated against the errors it is meant to predict.
 */
export function refinedConfidence(logRatio: number): number {
  return Math.exp(logRatio);
}

/**
 * Turns the output of both stages into metric predictions. Lines are numbered
 * from 1.
 *
 * - A refined line takes stage 2's start and its confidence.
 * - A line stage 2 could not check but stage 1 anchored goes back to stage 1's
 *   start with confidence 0, so a position nothing confirmed is not counted
 *   as a trusted one.
 * - A line stage 1 did not place has no start.
 */
export function toRefinedPredictions(
  anchored: readonly AnchoredLine[],
  refined: readonly RefinedLine[],
): Prediction[] {
  if (anchored.length !== refined.length) {
    throw new Error(
      `Stage 1 has ${anchored.length} lines but stage 2 has ${refined.length} lines`,
    );
  }
  return anchored.map((first, index): Prediction => {
    const line = index + 1;
    const second = refined[index];
    if (second?.status === "refined") {
      return {
        line,
        start: second.start,
        confidence: refinedConfidence(second.logRatio),
      };
    }
    if (first.status === "anchor") {
      return { line, start: first.start, confidence: 0 };
    }
    return { line, start: null };
  });
}

export type StatusCounts = {
  refined: number;
  no_window: number;
  no_text: number;
  too_long: number;
  too_short: number;
  /** Characters the model has no token for, summed over the lines. */
  skippedChars: number;
};

const STATUS_FIELDS: readonly RefinedLine["status"][] = [
  "refined",
  "no_window",
  "no_text",
  "too_long",
  "too_short",
];

/** How many lines ended in each status, and the skipped characters. */
export function countStatuses(lines: readonly RefinedLine[]): StatusCounts {
  const counts: StatusCounts = {
    refined: 0,
    no_window: 0,
    no_text: 0,
    too_long: 0,
    too_short: 0,
    skippedChars: 0,
  };
  for (const line of lines) {
    counts[line.status] += 1;
    counts.skippedChars += line.skippedChars;
  }
  return counts;
}

/** The sum of `counts`, field by field. */
export function addStatusCounts(counts: readonly StatusCounts[]): StatusCounts {
  const total = countStatuses([]);
  for (const one of counts) {
    for (const field of STATUS_FIELDS) total[field] += one[field];
    total.skippedChars += one.skippedChars;
  }
  return total;
}

function row(counts: StatusCounts): string {
  const parts = STATUS_FIELDS.map((field) => `${field} ${counts[field]}`);
  return `${parts.join(", ")}, skipped chars ${counts.skippedChars}`;
}

/** A plain-text table: one row per song, then the total. */
export function formatStatusCounts(
  songs: readonly { slug: string; counts: StatusCounts }[],
): string {
  const lines = ["Refine statuses"];
  for (const { slug, counts } of songs) {
    lines.push(`  ${slug}: ${row(counts)}`);
  }
  lines.push(
    `  Overall: ${row(addStatusCounts(songs.map(({ counts }) => counts)))}`,
  );
  return `${lines.join("\n")}\n`;
}
