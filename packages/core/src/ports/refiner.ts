import type { Ms } from "../domain/time";

/**
 * The span of the audio in which one lyric line is known to lie, as found by
 * the first stage. `end` is not before `start`.
 */
export type LineWindow = { start: Ms; end: Ms };

export type RefineRequest = {
  /** Path of the vocals audio. */
  audioPath: string;
  /** Directory of the forced-alignment model. */
  modelDir: string;
  /** One display line each, in order. */
  lyrics: readonly string[];
  /** One entry per lyric line; `null` for a line the first stage did not place. */
  windows: readonly (LineWindow | null)[];
  /**
   * What is forced: "surface" keeps the kanji as written, "kana" uses the
   * dictionary reading.
   */
  spelling: "surface" | "kana";
  /** Characters the user marked as not sung, one character each. */
  ignored: readonly string[];
  /** Room added before and after each window. */
  margin: Ms;
};

/**
 * What the second stage did with one lyric line. `logRatio` is the per-frame
 * log likelihood ratio of the forced path against the best path (0 or less;
 * nearer 0 is better). `skippedChars` counts the characters the model has no
 * token for, which were left out of the forcing.
 *
 * The other statuses carry no times: `no_window` (the line had no window),
 * `no_text` (no character of the line could be forced), `too_long` (the window
 * is longer than the worker accepts) and `too_short` (the window cannot hold
 * the line's characters).
 */
export type RefinedLine =
  | {
      status: "refined";
      start: Ms;
      end: Ms;
      logRatio: number;
      skippedChars: number;
    }
  | {
      status: "no_window" | "no_text" | "too_long" | "too_short";
      skippedChars: number;
    };

/** Places each lyric line precisely inside the window the first stage found. */
export interface Refiner {
  /** One result per lyric line, in order. */
  refine(request: RefineRequest): Promise<RefinedLine[]>;
}
