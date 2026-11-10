import type { Anchorer } from "@lirisync/core";
import {
  type KindSummary,
  perturbationOutcome,
  summarizeKind,
} from "./collateral";
import type { Prediction } from "./metrics";
import {
  PERTURBATION_KINDS,
  type Perturbation,
  type PerturbationKind,
} from "./perturbations";
import { toPredictions } from "./predictions";
import type { Song } from "./song-set";

/**
 * One perturbation and what it did. Line numbers only, never lyric text: the
 * report may be committed.
 */
export type PerturbationRecord = {
  kind: PerturbationKind;
  /** 1-based original line where the edit starts. */
  at: number;
  /** Original lines the edit spans. */
  span: number;
  collateral: number;
  collateralLines: number[];
  improved: number;
};

export type SongPerturbations = {
  slug: string;
  perturbations: PerturbationRecord[];
};

export type PerturbationReport = {
  kinds: KindSummary[];
  songs: SongPerturbations[];
};

/**
 * Runs the aligner's first stage on each perturbed version of a song (same
 * words, nothing ignored) and compares it with the baseline. The labeled-lines
 * check is not applied: the lines are mapped, not labeled, in a perturbed run.
 * `onEach` is called after every perturbation, with the number done so far.
 */
export async function runSongPerturbations(
  anchorer: Anchorer,
  song: Pick<Song, "slug" | "words" | "truth">,
  baseline: Prediction[],
  plan: readonly Perturbation[],
  onEach?: (done: number) => void,
): Promise<PerturbationRecord[]> {
  const records: PerturbationRecord[] = [];
  for (const perturbation of plan) {
    const { kind, at, span } = perturbation;
    let perturbed: Prediction[];
    try {
      perturbed = toPredictions(
        await anchorer.anchor({
          lyrics: perturbation.lyrics,
          words: song.words,
          ignored: [],
        }),
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`${song.slug}: ${kind} at line ${at}: ${reason}`);
    }
    records.push({
      kind,
      at,
      span,
      ...perturbationOutcome(song.truth, baseline, perturbation, perturbed),
    });
    onEach?.(records.length);
  }
  return records;
}

/** Summarizes each kind over all songs, in the order of `PERTURBATION_KINDS`. */
export function buildPerturbationReport(
  songs: SongPerturbations[],
): PerturbationReport {
  const all = songs.flatMap((song) => song.perturbations);
  return {
    kinds: PERTURBATION_KINDS.map((kind) =>
      summarizeKind(
        kind,
        all.filter((record) => record.kind === kind),
      ),
    ),
    songs,
  };
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * A plain-text section: one row per kind. "over one" is the share of
 * perturbations that cost more than one line, the adoption criterion.
 */
export function formatPerturbationReport(report: PerturbationReport): string {
  const lines = [
    "Perturbation (collateral: a line good in the baseline that is no longer good)",
  ];
  for (const summary of report.kinds) {
    const { kind, perturbations, overOneRate } = summary;
    if (
      overOneRate === null ||
      summary.meanCollateral === null ||
      summary.maxCollateral === null
    ) {
      lines.push(`  ${kind}: ${perturbations} perturbations, over one —`);
      continue;
    }
    lines.push(
      `  ${kind}: ${perturbations} perturbations, ` +
        `over one ${percent(overOneRate)} (${summary.overOne}/${perturbations}), ` +
        `with collateral ${summary.withCollateral}, ` +
        `mean ${summary.meanCollateral.toFixed(2)}, ` +
        `max ${summary.maxCollateral}, ` +
        `improved ${summary.improved}`,
    );
  }
  return `${lines.join("\n")}\n`;
}
