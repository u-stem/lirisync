import type { Anchorer, AsrWord, RefineRequest, Refiner } from "@lirisync/core";
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
import { toRefinedPredictions, windowsFromAnchors } from "./refinement";
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

/** What each stage predicts for one version of the lyrics. */
export type StagePredictions = {
  anchor: Prediction[];
  /** `null` when stage 2 is not measured. */
  refine: Prediction[] | null;
};

/** Predicts the line starts of a version of the lyrics, stage by stage. */
export type Predict = (lyrics: readonly string[]) => Promise<StagePredictions>;

/**
 * Builds a `Predict` that anchors the lyrics (same words, nothing ignored) and,
 * when `refine` is given, refines the lines stage 1 anchored with one call of
 * the refiner. `refine.request` is everything of the request but the lyrics
 * and the windows.
 */
export function stagePredictor(
  anchorer: Anchorer,
  words: AsrWord[],
  refine: {
    refiner: Refiner;
    request: Omit<RefineRequest, "lyrics" | "windows">;
    /** Shift added to every refined start, as in the baseline. */
    offsetMs?: number;
    /** Shift of every window start, as in the baseline (see `windowsFromAnchors`). */
    startShiftMs?: number;
  } | null,
): Predict {
  return async (lyrics) => {
    const anchored = await anchorer.anchor({ lyrics, words, ignored: [] });
    const anchor = toPredictions(anchored);
    if (refine === null) {
      return { anchor, refine: null };
    }
    const lines = await refine.refiner.refine({
      ...refine.request,
      lyrics,
      windows: windowsFromAnchors(anchored, refine.startShiftMs),
    });
    return {
      anchor,
      refine: toRefinedPredictions(anchored, lines, refine.offsetMs),
    };
  };
}

/**
 * Predicts each perturbed version of a song and compares it with the baseline,
 * for stage 1 and, when the baseline has stage 2, for stage 2. The
 * labeled-lines check is not applied: the lines are mapped, not labeled, in a
 * perturbed run.
 */
export async function runSongPerturbations(
  predict: Predict,
  song: Pick<Song, "slug" | "truth">,
  baseline: StagePredictions,
  plan: readonly Perturbation[],
): Promise<{
  anchor: PerturbationRecord[];
  refine: PerturbationRecord[] | null;
}> {
  const anchor: PerturbationRecord[] = [];
  const refine: PerturbationRecord[] | null =
    baseline.refine === null ? null : [];
  for (const perturbation of plan) {
    const { kind, at, span } = perturbation;
    let perturbed: StagePredictions;
    try {
      perturbed = await predict(perturbation.lyrics);
      if (baseline.refine !== null && perturbed.refine === null) {
        throw new Error("no stage 2 predictions");
      }
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`${song.slug}: ${kind} at line ${at}: ${reason}`);
    }
    anchor.push({
      kind,
      at,
      span,
      ...perturbationOutcome(
        song.truth,
        baseline.anchor,
        perturbation,
        perturbed.anchor,
      ),
    });
    if (
      refine !== null &&
      baseline.refine !== null &&
      perturbed.refine !== null
    ) {
      refine.push({
        kind,
        at,
        span,
        ...perturbationOutcome(
          song.truth,
          baseline.refine,
          perturbation,
          perturbed.refine,
        ),
      });
    }
  }
  return { anchor, refine };
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
export function formatPerturbationReport(
  report: PerturbationReport,
  title = "Perturbation",
): string {
  const lines = [
    `${title} (collateral: a line good in the baseline that is no longer good)`,
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
