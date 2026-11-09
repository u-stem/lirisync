import type { Ms } from "../domain/time";

/** One word heard by the ASR. `end` is not before `start`. */
export type AsrWord = { start: Ms; end: Ms; text: string };

export type AnchorRequest = {
  /** One display line each, in order. */
  lyrics: readonly string[];
  /** Ordered by non-decreasing `start`; overlaps are allowed. */
  words: readonly AsrWord[];
  /** Characters the user marked as not sung, one character each. */
  ignored: readonly string[];
};

/**
 * Where the first stage of alignment put one lyric line. `matchRatio` is the
 * share of the line's characters that matched the ASR exactly (0 to 1).
 * `ambiguous` marks a line that an equally good alignment would place elsewhere.
 */
export type AnchoredLine =
  | {
      status: "anchor";
      start: Ms;
      end: Ms;
      matchRatio: number;
      ambiguous: boolean;
    }
  | { status: "unmatched"; matchRatio: number; ambiguous: boolean }
  | { status: "not_sung" };

/** Places every lyric line on the timeline from the ASR words. */
export interface Anchorer {
  /** One result per lyric line, in order. */
  anchor(request: AnchorRequest): Promise<AnchoredLine[]>;
}
