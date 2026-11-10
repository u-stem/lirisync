import type { RefinedLine, RefineRequest, Refiner } from "@lirisync/core";
import { type WorkerClient, WorkerProtocolError } from "./worker-client";
import { type RefineParams, RefineResult } from "./worker-protocol";

type WireLine = RefineResult["lines"][number];

function toRefinedLine(wire: WireLine, index: number): RefinedLine {
  const where = `Line ${index + 1}`;
  const { status, startMs, endMs, logRatio, skippedChars } = wire;
  if (status === "refined") {
    if (startMs === null || endMs === null || logRatio === null) {
      throw new WorkerProtocolError(
        `${where} is refined without times and a ratio`,
      );
    }
    if (endMs < startMs) {
      throw new WorkerProtocolError(`${where} ends before it starts`);
    }
    return { status, start: startMs, end: endMs, logRatio, skippedChars };
  }
  if (startMs !== null || endMs !== null || logRatio !== null) {
    throw new WorkerProtocolError(
      `${where} is ${status} but has times or a ratio`,
    );
  }
  return { status, skippedChars };
}

/** `Refiner` backed by the worker's `refine` method. */
export class WorkerRefiner implements Refiner {
  readonly #client: Pick<WorkerClient, "request">;

  constructor(client: Pick<WorkerClient, "request">) {
    this.#client = client;
  }

  async refine(request: RefineRequest): Promise<RefinedLine[]> {
    const params: RefineParams = {
      audio: request.audioPath,
      model: request.modelDir,
      lyrics: [...request.lyrics],
      windows: request.windows.map((window) =>
        window === null ? null : { startMs: window.start, endMs: window.end },
      ),
      spelling: request.spelling,
      ignored: [...request.ignored],
      marginMs: request.margin,
    };
    const parsed = RefineResult.safeParse(
      await this.#client.request("refine", params),
    );
    if (!parsed.success) {
      throw new WorkerProtocolError(
        `The refine result is not usable: ${parsed.error.message}`,
      );
    }
    const { lines } = parsed.data;
    if (lines.length !== request.lyrics.length) {
      throw new WorkerProtocolError(
        `The refine result has ${lines.length} lines for ${request.lyrics.length} lyric lines`,
      );
    }
    return lines.map(toRefinedLine);
  }
}
