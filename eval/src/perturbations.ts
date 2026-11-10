import type { TruthLine } from "./labels";
import { normalizeLine } from "./repeats";

export type PerturbationKind = "delete" | "duplicate" | "collapse";

export const PERTURBATION_KINDS: readonly PerturbationKind[] = [
  "delete",
  "duplicate",
  "collapse",
];

/** The longest repeated block that `collapse` looks for. */
const MAX_BLOCK_LINES = 4;

/** An edit that real lyrics have, applied to one song's lyric lines. */
export type Perturbation = {
  kind: PerturbationKind;
  /** 1-based original line where the edit starts. */
  at: number;
  /** Original lines the edit spans: 1, or the block length for `collapse`. */
  span: number;
  /** The perturbed lyric lines, to give to the aligner. */
  lyrics: string[];
  /**
   * For every original labeled line that is still comparable, its 1-based
   * number in `lyrics`.
   */
  lineMap: Map<number, number>;
  /** Original labeled lines the edit touches; they are not counted. */
  excluded: number[];
};

/** Where original line `line` ends up when `shift` applies to lines after `after`. */
function shiftedLine(line: number, after: number, shift: number): number {
  return line > after ? line + shift : line;
}

function build(
  kind: PerturbationKind,
  at: number,
  span: number,
  lyrics: string[],
  labeled: readonly number[],
  touched: (line: number) => boolean,
  newNumber: (line: number) => number,
): Perturbation {
  const lineMap = new Map<number, number>();
  const excluded: number[] = [];
  for (const line of labeled) {
    if (touched(line)) excluded.push(line);
    else lineMap.set(line, newNumber(line));
  }
  return { kind, at, span, lyrics, lineMap, excluded };
}

function deletions(
  lyrics: readonly string[],
  labeled: readonly number[],
): Perturbation[] {
  // Deleting the only line leaves nothing to align against.
  if (lyrics.length < 2) return [];
  return labeled.map((k) =>
    build(
      "delete",
      k,
      1,
      lyrics.filter((_, index) => index !== k - 1),
      labeled,
      (line) => line === k,
      (line) => shiftedLine(line, k, -1),
    ),
  );
}

function duplications(
  lyrics: readonly string[],
  labeled: readonly number[],
): Perturbation[] {
  return labeled.map((k) =>
    build(
      "duplicate",
      k,
      1,
      lyrics.flatMap((text, index) =>
        index === k - 1 ? [text, text] : [text],
      ),
      labeled,
      (line) => line === k,
      (line) => shiftedLine(line, k, 1),
    ),
  );
}

function collapses(
  lyrics: readonly string[],
  labeled: readonly number[],
): Perturbation[] {
  const normalized = lyrics.map(normalizeLine);
  const found: Perturbation[] = [];
  for (let start = 0; start < lyrics.length; start += 1) {
    for (let span = 1; span <= MAX_BLOCK_LINES; span += 1) {
      const end = start + span;
      if (end + span > lyrics.length) break;
      const first = normalized.slice(start, end);
      const second = normalized.slice(end, end + span);
      if (first.every((text) => text === "")) continue;
      if (first.some((text, offset) => text !== second[offset])) continue;
      found.push(
        build(
          "collapse",
          start + 1,
          span,
          lyrics.filter((_, index) => index < end || index >= end + span),
          labeled,
          (line) => line > start && line <= end + span,
          (line) => shiftedLine(line, end + span, -span),
        ),
      );
    }
  }
  return found;
}

/**
 * Every perturbation of one song: each labeled line deleted, each labeled line
 * duplicated, and each immediately repeated block (1 to 4 lines) written once.
 * Lines without a label are never targeted but move with the edit.
 */
export function perturbations(
  lyrics: readonly string[],
  truth: readonly TruthLine[],
): Perturbation[] {
  const labeled = truth.map(({ line }) => line);
  return [
    ...deletions(lyrics, labeled),
    ...duplications(lyrics, labeled),
    ...collapses(lyrics, labeled),
  ];
}
