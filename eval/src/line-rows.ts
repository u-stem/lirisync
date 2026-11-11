import { predictionsByLine } from "./metrics";
import type { SongResult } from "./report";

/**
 * One labeled line: the true start and what each stage predicted. Line
 * numbers only, never lyric text, so the rows may be committed with the
 * results.
 */
export type LineRow = {
  line: number;
  trueMs: number;
  stage1Ms: number | null;
  stage1Confidence: number | null;
  /** Present only when stage 2 was measured. */
  stage2Ms?: number | null;
  stage2Confidence?: number | null;
};

export type SongLines = { slug: string; lines: LineRow[] };

/**
 * The labeled lines of every song with both stages' predictions, for
 * analysis line by line (for example, the error against how a line starts).
 * `stageTwo`, when given, must hold the same songs in the same order.
 */
export function lineRows(
  stageOne: readonly SongResult[],
  stageTwo: readonly SongResult[] | null,
): SongLines[] {
  return stageOne.map((song, index) => {
    const second = stageTwo?.[index];
    if (stageTwo !== null && second?.slug !== song.slug) {
      throw new Error(
        `stage 2 results are for song ${second?.slug ?? "(none)"}, not ${song.slug}`,
      );
    }
    const firstByLine = predictionsByLine(song.predictions);
    const secondByLine =
      second === undefined ? null : predictionsByLine(second.predictions);
    const lines = [...song.truth]
      .sort((a, b) => a.line - b.line)
      .map(({ line, start }): LineRow => {
        const first = firstByLine.get(line);
        const row: LineRow = {
          line,
          trueMs: start,
          stage1Ms: first?.start ?? null,
          stage1Confidence: first?.confidence ?? null,
        };
        if (secondByLine === null) return row;
        const refined = secondByLine.get(line);
        return {
          ...row,
          stage2Ms: refined?.start ?? null,
          stage2Confidence: refined?.confidence ?? null,
        };
      });
    return { slug: song.slug, lines };
  });
}
