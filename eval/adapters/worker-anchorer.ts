import type { AnchoredLine, Anchorer, AnchorRequest } from "@lirisync/core";
import { type WorkerClient, WorkerProtocolError } from "./worker-client";
import { type AnchorParams, AnchorResult } from "./worker-protocol";

type WireLine = AnchorResult["lines"][number];

function toAnchoredLine(wire: WireLine, index: number): AnchoredLine {
  const where = `Line ${index + 1}`;
  const { status, startMs, endMs, matchRatio, ambiguous } = wire;
  if (status === "anchor") {
    if (startMs === null || endMs === null) {
      throw new WorkerProtocolError(`${where} is anchored without times`);
    }
    if (endMs < startMs) {
      throw new WorkerProtocolError(`${where} ends before it starts`);
    }
    return { status, start: startMs, end: endMs, matchRatio, ambiguous };
  }
  if (startMs !== null || endMs !== null) {
    throw new WorkerProtocolError(`${where} is ${status} but has times`);
  }
  return status === "unmatched"
    ? { status, matchRatio, ambiguous }
    : { status };
}

/** `Anchorer` backed by the worker's `anchor` method. */
export class WorkerAnchorer implements Anchorer {
  readonly #client: Pick<WorkerClient, "request">;

  constructor(client: Pick<WorkerClient, "request">) {
    this.#client = client;
  }

  async anchor(request: AnchorRequest): Promise<AnchoredLine[]> {
    const params: AnchorParams = {
      lyrics: [...request.lyrics],
      words: request.words.map(({ start, end, text }) => ({
        startMs: start,
        endMs: end,
        text,
      })),
      ignored: [...request.ignored],
    };
    const parsed = AnchorResult.safeParse(
      await this.#client.request("anchor", params),
    );
    if (!parsed.success) {
      throw new WorkerProtocolError(
        `The anchor result is not usable: ${parsed.error.message}`,
      );
    }
    const { lines } = parsed.data;
    if (lines.length !== request.lyrics.length) {
      throw new WorkerProtocolError(
        `The anchor result has ${lines.length} lines for ${request.lyrics.length} lyric lines`,
      );
    }
    return lines.map(toAnchoredLine);
  }
}
