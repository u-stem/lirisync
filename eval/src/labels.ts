import type { Ms } from "@lirisync/core";
import { parseSecondsText } from "./seconds";

/** Ground truth for one lyric line: when it starts singing. */
export type TruthLine = { line: number; start: Ms };

const LINE_NUMBER = /^[1-9]\d*$/;

/**
 * Parses an Audacity label file (`start<TAB>end<TAB>label` per row, seconds).
 *
 * The label text is the 1-based line number in the song's `lyrics.txt`, not
 * the lyric itself: label files are committed and lyrics are not. Only the
 * start time is kept; a region label's end is checked for order and dropped.
 *
 * Throws on any row it cannot read, naming the 1-based row, so that a typo in
 * a label never silently shrinks the evaluation set.
 */
export function parseAudacityLabels(text: string): TruthLine[] {
  const byLine = new Map<number, TruthLine>();
  const rows = text.split(/\r?\n/);
  rows.forEach((row, index) => {
    if (row.trim() === "") return;
    const where = `row ${index + 1}`;
    const fields = row.split("\t");
    const [startText, endText, label] = fields;
    if (
      fields.length !== 3 ||
      startText === undefined ||
      endText === undefined ||
      label === undefined
    ) {
      throw new Error(`${where}: expected start, end and label: ${row}`);
    }
    let start: Ms;
    let end: Ms;
    try {
      start = parseSecondsText(startText);
      end = parseSecondsText(endText);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`${where}: ${reason}`);
    }
    if (end < start) {
      throw new Error(`${where}: end before start`);
    }
    if (!LINE_NUMBER.test(label)) {
      throw new Error(`${where}: label must be a line number: ${label}`);
    }
    const line = Number(label);
    if (byLine.has(line)) {
      throw new Error(`${where}: line ${line} is labeled twice`);
    }
    byLine.set(line, { line, start });
  });
  return [...byLine.values()].sort((a, b) => a.line - b.line);
}

/**
 * Splits `lyrics.txt` into its lines. A final newline ends the last line; it
 * does not start an empty one.
 */
export function splitLyricsLines(lyrics: string): string[] {
  const lines = lyrics.split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/**
 * Checks that every label points at a non-blank line of `lyrics.txt`. A label
 * on a missing or blank line can never be predicted, so it would silently
 * lower the match rate instead of failing.
 */
export function assertLabelsSung(labels: TruthLine[], lyrics: string): void {
  const lines = splitLyricsLines(lyrics);
  for (const { line } of labels) {
    const text = lines[line - 1];
    if (text === undefined) {
      throw new Error(
        `Label for line ${line} is past the end of lyrics.txt (${lines.length} lines)`,
      );
    }
    if (text.trim() === "") {
      throw new Error(`Label for line ${line} is blank in lyrics.txt`);
    }
  }
}

/** The 1-based lines of `lyrics.txt` that are sung (not blank) but have no label. */
export function unlabeledLines(labels: TruthLine[], lyrics: string): number[] {
  const labeled = new Set(labels.map((label) => label.line));
  return splitLyricsLines(lyrics)
    .map((text, index) => ({ text, line: index + 1 }))
    .filter(({ text, line }) => text.trim() !== "" && !labeled.has(line))
    .map(({ line }) => line);
}
