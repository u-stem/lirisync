import { type ErrorProfile, errorProfile } from "./errors";
import type { TruthLine } from "./labels";
import {
  type Prediction,
  passesAccuracyGate,
  type Score,
  score,
} from "./metrics";
import { type Confusion, confusion, repeatGroups } from "./repeats";

export type SongResult = {
  slug: string;
  lyricsText: string;
  truth: TruthLine[];
  predictions: Prediction[];
};

export type Report = {
  overall: {
    score: Score;
    errors: ErrorProfile;
    repeats: Confusion;
    passesGate: boolean;
  };
  songs: { slug: string; score: Score; errors: ErrorProfile }[];
};

/**
 * Scores every song alone and all songs pooled. The pooled numbers are the
 * ones the accuracy gate is judged on; repeat groups are found per song, since
 * a line repeated across two songs is not a repeat.
 */
export function buildReport(results: SongResult[]): Report {
  const runs = results.map(({ truth, predictions }) => ({
    truth,
    predictions,
  }));
  const overallScore = score(runs);
  return {
    overall: {
      score: overallScore,
      errors: errorProfile(runs),
      repeats: confusion(
        results.map(({ truth, predictions, lyricsText }) => ({
          truth,
          predictions,
          groups: repeatGroups(lyricsText),
        })),
      ),
      passesGate: passesAccuracyGate(overallScore),
    },
    songs: results.map(({ slug, truth, predictions }) => {
      const run = [{ truth, predictions }];
      return { slug, score: score(run), errors: errorProfile(run) };
    }),
  };
}

const MISSING = "—";

function ms(value: number | null): string {
  return value === null ? MISSING : `${Math.round(value)} ms`;
}

function percent(value: number | null): string {
  return value === null ? MISSING : `${(value * 100).toFixed(1)}%`;
}

function auroc(value: number | null): string {
  return value === null ? MISSING : value.toFixed(3);
}

/** A plain-text summary: one row per song, then the pooled block. */
export function formatReport(report: Report): string {
  const { overall, songs } = report;
  const lines: string[] = ["Songs"];
  for (const song of songs) {
    lines.push(
      `  ${song.slug}: matched ${song.score.matched}/${song.score.labeled} ` +
        `(${percent(song.score.matchRate)}), ` +
        `median ${ms(song.score.medianStartErrorMs)}, ` +
        `P90 ${ms(song.errors.p90StartErrorMs)}, ` +
        `gross ${percent(song.errors.grossErrorRate)}`,
    );
  }
  lines.push(
    "",
    "Overall",
    `  Matched: ${overall.score.matched}/${overall.score.labeled} (${percent(overall.score.matchRate)})`,
    `  Median start error: ${ms(overall.score.medianStartErrorMs)}`,
    `  P90 start error: ${ms(overall.errors.p90StartErrorMs)}`,
    `  Gross error rate: ${percent(overall.errors.grossErrorRate)}`,
    `  Silent error rate: ${percent(overall.errors.silentErrorRate)}`,
    `  Confidence AUROC: ${auroc(overall.errors.confidenceAuroc)}`,
    `  Repeat confusion: ${percent(overall.repeats.rate)} (${overall.repeats.confused}/${overall.repeats.considered})`,
    "",
    `Gate: ${overall.passesGate ? "PASS" : "FAIL"}`,
  );
  return `${lines.join("\n")}\n`;
}
