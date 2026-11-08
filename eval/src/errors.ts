import type { SongRun } from "./metrics";
import { predictionsByLine } from "./metrics";

/** A matched line further off than this is a gross error. */
export const GROSS_ERROR_MS = 1000;

export type ErrorProfileOptions = {
  /**
   * Lines at or above this confidence are the ones a user would not check.
   * Initial value, to be tuned on the evaluation set.
   */
  highConfidence: number;
};

const DEFAULT_OPTIONS: ErrorProfileOptions = { highConfidence: 0.8 };

export type ErrorProfile = {
  /** Nearest-rank 90th percentile of |predicted - true| over matched lines. */
  p90StartErrorMs: number | null;
  /** Share of matched lines off by more than GROSS_ERROR_MS. */
  grossErrorRate: number | null;
  /**
   * Share of high-confidence lines that are gross errors: the mistakes a user
   * trusting the confidence would not look at.
   */
  silentErrorRate: number | null;
  /**
   * Probability that a random correct line has higher confidence than a
   * random gross error (ties count half). 0.5 is no better than chance.
   */
  confidenceAuroc: number | null;
};

type MatchedLine = {
  line: number;
  errorMs: number;
  confidence: number | undefined;
};

type ScoredLine = { errorMs: number; confidence: number };

function matchedLines(runs: SongRun[]): MatchedLine[] {
  const matched: MatchedLine[] = [];
  for (const { truth, predictions } of runs) {
    const byLine = predictionsByLine(predictions);
    for (const { line, start } of truth) {
      const prediction = byLine.get(line);
      if (prediction === undefined || prediction.start === null) continue;
      matched.push({
        line,
        errorMs: Math.abs(prediction.start - start),
        confidence: prediction.confidence,
      });
    }
  }
  return matched;
}

/**
 * The matched lines with their confidence, or null when the aligner reports
 * none. Reporting it for only some lines is an aligner bug, not a weak score.
 */
function withConfidence(lines: MatchedLine[]): ScoredLine[] | null {
  if (lines.every((line) => line.confidence === undefined)) return null;
  return lines.map(({ line, errorMs, confidence }) => {
    if (confidence === undefined) {
      throw new Error(`Prediction for line ${line} has no confidence`);
    }
    return { errorMs, confidence };
  });
}

function percentile(values: number[], fraction: number): number | null {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.ceil(fraction * sorted.length) - 1] ?? null;
}

function auroc(correct: number[], gross: number[]): number | null {
  if (correct.length === 0 || gross.length === 0) return null;
  let wins = 0;
  for (const c of correct) {
    for (const g of gross) {
      if (c > g) wins += 1;
      else if (c === g) wins += 0.5;
    }
  }
  return wins / (correct.length * gross.length);
}

/**
 * Tail and confidence metrics over the labeled lines of every song, pooled
 * like `score`. Unmatched lines are left to the match rate.
 */
export function errorProfile(
  runs: SongRun[],
  options: ErrorProfileOptions = DEFAULT_OPTIONS,
): ErrorProfile {
  const lines = matchedLines(runs);
  const isGross = (line: { errorMs: number }) => line.errorMs > GROSS_ERROR_MS;
  const scored = withConfidence(lines);
  const confident = scored?.filter(
    (line) => line.confidence >= options.highConfidence,
  );
  const confidenceOf = (line: ScoredLine) => line.confidence;
  return {
    p90StartErrorMs: percentile(
      lines.map((line) => line.errorMs),
      0.9,
    ),
    grossErrorRate:
      lines.length === 0 ? null : lines.filter(isGross).length / lines.length,
    silentErrorRate:
      confident === undefined || confident.length === 0
        ? null
        : confident.filter(isGross).length / confident.length,
    confidenceAuroc:
      scored === null
        ? null
        : auroc(
            scored.filter((line) => !isGross(line)).map(confidenceOf),
            scored.filter(isGross).map(confidenceOf),
          ),
  };
}
