import type { SongRun } from "./metrics";
import { median, predictionsByLine } from "./metrics";

/** A matched line further off than this is a gross error. */
export const GROSS_ERROR_MS = 1000;

export type ErrorProfileOptions = {
  /**
   * Lines at or above this confidence are the ones a user would not check.
   * Initial value, to be tuned on the evaluation set.
   */
  highConfidence: number;
};

/** The confidence at or above which a line counts as one a user would not check. */
export const DEFAULT_HIGH_CONFIDENCE = 0.8;

const DEFAULT_OPTIONS: ErrorProfileOptions = {
  highConfidence: DEFAULT_HIGH_CONFIDENCE,
};

/** How the confidence of the matched lines is spread, to see how it is scaled. */
export type ConfidenceSpread = {
  min: number;
  median: number;
  max: number;
  /** Lines at or above `threshold`. */
  high: number;
  /** The high-confidence threshold `high` was counted with. */
  threshold: number;
  lines: number;
};

export type ErrorProfile = {
  /**
   * Median of predicted - true line start over matched lines: negative is
   * early. A bias shared by most lines (the aligner's, or the labels' own,
   * such as labels placed late while listening) shows here, not in the
   * absolute errors.
   */
  medianSignedErrorMs: number | null;
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
  /** Null when the aligner reports no confidence or no line matched. */
  confidenceSpread: ConfidenceSpread | null;
};

type MatchedLine = {
  /** 1-based position of the song in `runs`, for error messages. */
  song: number;
  line: number;
  /** predicted - true; negative is early. */
  signedMs: number;
  errorMs: number;
  confidence: number | undefined;
};

type ScoredLine = { errorMs: number; confidence: number };

function matchedLines(runs: SongRun[]): MatchedLine[] {
  const matched: MatchedLine[] = [];
  runs.forEach(({ truth, predictions }, index) => {
    const byLine = predictionsByLine(predictions);
    for (const { line, start } of truth) {
      const prediction = byLine.get(line);
      if (prediction === undefined || prediction.start === null) continue;
      const signedMs = prediction.start - start;
      matched.push({
        song: index + 1,
        line,
        signedMs,
        errorMs: Math.abs(signedMs),
        confidence: prediction.confidence,
      });
    }
  });
  return matched;
}

/**
 * The matched lines with their confidence, or null when the aligner reports
 * none. Reporting it for only some lines, or outside 0 to 1, is an aligner
 * bug, not a weak score.
 */
function withConfidence(lines: MatchedLine[]): ScoredLine[] | null {
  if (lines.every((line) => line.confidence === undefined)) return null;
  return lines.map(({ song, line, errorMs, confidence }) => {
    const where = `Prediction for song ${song}, line ${line}`;
    if (confidence === undefined) {
      throw new Error(`${where} has no confidence`);
    }
    // Written as a positive range test so that NaN fails it too.
    if (!(confidence >= 0 && confidence <= 1)) {
      throw new Error(`${where} has confidence ${confidence} outside 0 to 1`);
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
  const confidences = scored?.map(confidenceOf) ?? [];
  const middle = median(confidences);
  return {
    medianSignedErrorMs: median(lines.map((line) => line.signedMs)),
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
    confidenceSpread:
      middle === null
        ? null
        : {
            min: Math.min(...confidences),
            median: middle,
            max: Math.max(...confidences),
            high: confident?.length ?? 0,
            threshold: options.highConfidence,
            lines: confidences.length,
          },
  };
}
