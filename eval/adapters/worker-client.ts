import {
  type ErrorCode,
  HelloResult,
  PROTOCOL_PREFIX,
  PROTOCOL_VERSION,
  Response,
} from "./worker-protocol";

/** The worker answered a request with an `error` message. */
export class WorkerError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
  ) {
    super(`${code}: ${message}`);
    this.name = "WorkerError";
  }
}

/** The worker broke the protocol or went away; no further request can work. */
export class WorkerProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkerProtocolError";
  }
}

/** The ends of the worker's pipes. Bun's `FileSink` fits `stdin`. */
export type WorkerIo = {
  stdin: { write(text: string): unknown; flush(): unknown; end(): unknown };
  stdout: ReadableStream<Uint8Array>;
};

export type WorkerClientOptions = {
  /** Receives stdout lines without the protocol prefix, i.e. stray output. */
  onLog?: (line: string) => void;
};

type Pending = {
  resolve: (result: Record<string, unknown>) => void;
  reject: (error: Error) => void;
};

async function* readLines(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<string> {
  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of stream) {
    // `stream: true` keeps a character split across chunks for the next one.
    buffer += decoder.decode(chunk, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      yield buffer.slice(0, newline).replace(/\r$/, "");
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf("\n");
    }
  }
  buffer += decoder.decode();
  if (buffer !== "") yield buffer.replace(/\r$/, "");
}

/**
 * Speaks the worker protocol over a pair of pipes: one JSON request per line
 * in, prefixed JSON responses out, matched by id.
 *
 * Any protocol violation, an error without an id, or the end of the output
 * fails every pending request and every later one: the worker's state is
 * unknown from then on.
 */
export class WorkerClient {
  readonly #stdin: WorkerIo["stdin"];
  readonly #onLog: (line: string) => void;
  readonly #pending = new Map<string, Pending>();
  #nextId = 1;
  #failure: Error | null = null;
  /** Settles once the worker's output has ended or broken the protocol. */
  readonly done: Promise<void>;

  constructor(io: WorkerIo, options: WorkerClientOptions = {}) {
    this.#stdin = io.stdin;
    this.#onLog = options.onLog ?? (() => {});
    this.done = this.#read(io.stdout);
  }

  request(
    method: string,
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (this.#failure !== null) return Promise.reject(this.#failure);
    const id = String(this.#nextId);
    this.#nextId += 1;
    const answer = new Promise<Record<string, unknown>>((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
    });
    const request = { v: PROTOCOL_VERSION, id, method, params };
    try {
      this.#stdin.write(`${JSON.stringify(request)}\n`);
      this.#stdin.flush();
    } catch (error) {
      this.#pending.delete(id);
      return Promise.reject(error);
    }
    return answer;
  }

  /** Ends the worker's input; the worker exits when it has read all of it. */
  async close(): Promise<void> {
    await this.#stdin.end();
  }

  async #read(stdout: ReadableStream<Uint8Array>): Promise<void> {
    try {
      for await (const line of readLines(stdout)) this.#handle(line);
      this.#fail(new WorkerProtocolError("The worker's output ended"));
    } catch (error) {
      this.#fail(
        error instanceof Error ? error : new WorkerProtocolError(String(error)),
      );
    }
  }

  #handle(line: string): void {
    if (!line.startsWith(PROTOCOL_PREFIX)) {
      this.#onLog(line);
      return;
    }
    const message = this.#parse(line.slice(PROTOCOL_PREFIX.length));
    if (message.type === "progress") {
      if (!this.#pending.has(message.id)) {
        throw new WorkerProtocolError(
          `A progress message names unknown id ${message.id}`,
        );
      }
      return;
    }
    if (message.type === "error" && message.id === null) {
      // Only an unreadable request yields an error without an id. This client
      // writes every request itself, so that is a bug on either side.
      throw new WorkerError(message.code, message.message);
    }
    const pending = this.#take(message.id);
    if (message.type === "result") {
      pending.resolve(message.result);
    } else {
      pending.reject(new WorkerError(message.code, message.message));
    }
  }

  #parse(text: string): Response {
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      throw new WorkerProtocolError("A protocol line is not JSON");
    }
    const parsed = Response.safeParse(json);
    if (!parsed.success) {
      throw new WorkerProtocolError(
        `A protocol line is not a response: ${parsed.error.message}`,
      );
    }
    return parsed.data;
  }

  #take(id: string | null): Pending {
    const pending = id === null ? undefined : this.#pending.get(id);
    if (id === null || pending === undefined) {
      throw new WorkerProtocolError(`A response names unknown id ${id}`);
    }
    this.#pending.delete(id);
    return pending;
  }

  #fail(error: Error): void {
    this.#failure ??= error;
    for (const pending of this.#pending.values()) pending.reject(error);
    this.#pending.clear();
  }
}

/**
 * Asks the worker who it is. Rejects a worker that speaks another protocol
 * version or lacks any of `required`.
 */
export async function handshake(
  client: Pick<WorkerClient, "request">,
  required: readonly string[],
): Promise<HelloResult> {
  const parsed = HelloResult.safeParse(await client.request("hello", {}));
  if (!parsed.success) {
    throw new WorkerProtocolError(
      `The worker's hello is not usable: ${parsed.error.message}`,
    );
  }
  const missing = required.filter((m) => !parsed.data.methods.includes(m));
  if (missing.length > 0) {
    throw new WorkerProtocolError(
      `Worker ${parsed.data.worker} lacks methods: ${missing.join(", ")}`,
    );
  }
  return parsed.data;
}
