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
      throw new Error(`${where}: ${String(error)}`);
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
