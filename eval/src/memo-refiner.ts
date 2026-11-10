import type {
  LineWindow,
  RefinedLine,
  RefineRequest,
  Refiner,
} from "@lirisync/core";

/** What the worker gives a line without a window: it reads nothing of the line. */
const NO_WINDOW: RefinedLine = { status: "no_window", skippedChars: 0 };

/**
 * Wraps a `Refiner` and remembers the result of each line.
 *
 * The worker refines each line on its own: for the same audio, model,
 * spelling, margin and ignored characters, a line's result depends only on its
 * text and window. So a line already answered need not be sent again. Every
 * call costs the audio decoding in the worker, so a call is made only when
 * some line with a window is not remembered, and the remembered lines go with
 * no window (the worker does nothing for them); their results are replaced by
 * the remembered ones. A line without a window is answered here, as the
 * worker would answer it.
 */
export class MemoRefiner implements Refiner {
  readonly #inner: Refiner;
  readonly #memo = new Map<string, RefinedLine>();

  constructor(inner: Refiner) {
    this.#inner = inner;
  }

  async refine(request: RefineRequest): Promise<RefinedLine[]> {
    const { lyrics, windows } = request;
    if (windows.length !== lyrics.length) {
      throw new Error(
        `${windows.length} windows for ${lyrics.length} lyric lines`,
      );
    }
    const keys = lyrics.map((text, index) =>
      lineKey(request, text, windows[index] ?? null),
    );
    // The worker answers a line without a window with `no_window` and does
    // nothing else, so such a line needs no call.
    for (const [index, key] of keys.entries()) {
      if (windows[index] === null && !this.#memo.has(key)) {
        this.#memo.set(key, NO_WINDOW);
      }
    }
    const known = keys.map((key) => this.#memo.has(key));
    if (known.every(Boolean)) {
      return this.#recall(keys);
    }
    const sent = windows.map((window, index) =>
      known[index] === true ? null : window,
    );
    const lines = await this.#inner.refine({ ...request, windows: sent });
    if (lines.length !== lyrics.length) {
      throw new Error(
        `The refiner returned ${lines.length} lines for ${lyrics.length} lyric lines`,
      );
    }
    for (const [index, line] of lines.entries()) {
      const key = keys[index];
      if (key !== undefined && known[index] !== true) {
        this.#memo.set(key, line);
      }
    }
    return this.#recall(keys);
  }

  #recall(keys: readonly string[]): RefinedLine[] {
    return keys.map((key) => {
      const line = this.#memo.get(key);
      if (line === undefined) {
        throw new Error("A line result is missing from the memo");
      }
      return line;
    });
  }
}

/** Everything that decides the result of one line. */
function lineKey(
  request: RefineRequest,
  text: string,
  window: LineWindow | null,
): string {
  return JSON.stringify([
    request.audioPath,
    request.modelDir,
    request.spelling,
    request.margin,
    request.ignored,
    text,
    window === null ? null : [window.start, window.end],
  ]);
}
