import { describe, expect, test } from "bun:test";
import {
  handshake,
  WorkerClient,
  WorkerError,
  WorkerProtocolError,
} from "../../adapters/worker-client";

const PREFIX = "@@lirisync ";

type Sent = { id: string; method: string; params: unknown };

function isSent(value: unknown): value is Sent {
  return typeof value === "object" && value !== null && "id" in value;
}

/**
 * A worker that answers each request with the lines `respond` returns. Lines
 * are written as given, so a test controls prefixes, chunking and newlines.
 */
function fakeWorker(
  respond: (request: Sent) => (string | Uint8Array)[] = () => [],
) {
  const { readable, writable } = new TransformStream<Uint8Array>();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();
  const written: string[] = [];
  let ended = false;
  const emit = (out: string | Uint8Array) =>
    void writer.write(typeof out === "string" ? encoder.encode(out) : out);
  const stdin = {
    write(text: string) {
      written.push(text);
      const request: unknown = JSON.parse(text);
      if (!isSent(request)) throw new Error("not a request");
      for (const out of respond(request)) emit(out);
    },
    flush() {},
    end() {
      ended = true;
    },
  };
  return {
    io: { stdin, stdout: readable },
    written,
    emit,
    finish: () => void writer.close(),
    ended: () => ended,
  };
}

function protocolLine(message: object): string {
  return `${PREFIX}${JSON.stringify(message)}\n`;
}

function resultFor(request: Sent, result: object = {}): string {
  return protocolLine({ id: request.id, type: "result", result });
}

describe("WorkerClient", () => {
  test("writes one request line with protocol version 1", async () => {
    const worker = fakeWorker((r) => [resultFor(r)]);
    const client = new WorkerClient(worker.io);
    await client.request("hello", {});
    expect(worker.written).toEqual([
      '{"v":1,"id":"1","method":"hello","params":{}}\n',
    ]);
  });

  test("gives each request its own id", async () => {
    const worker = fakeWorker((r) => [resultFor(r)]);
    const client = new WorkerClient(worker.io);
    await client.request("hello", {});
    await client.request("hello", {});
    const ids = worker.written.map((text) => JSON.parse(text).id);
    expect(ids).toEqual(["1", "2"]);
  });

  test("resolves with the result of the matching id", async () => {
    const worker = fakeWorker((r) => [resultFor(r, { answer: 42 })]);
    const client = new WorkerClient(worker.io);
    const result = await client.request("hello", {});
    expect(result).toEqual({ answer: 42 });
  });

  test("passes lines without the prefix to the log", async () => {
    const worker = fakeWorker((r) => ["loading model\n", resultFor(r)]);
    const logs: string[] = [];
    const client = new WorkerClient(worker.io, { onLog: (l) => logs.push(l) });
    await client.request("hello", {});
    expect(logs).toEqual(["loading model"]);
  });

  test("skips progress messages", async () => {
    const progress = (r: Sent) =>
      protocolLine({
        id: r.id,
        type: "progress",
        stage: "asr",
        ratio: 0.5,
        etaMs: null,
      });
    const worker = fakeWorker((r) => [progress(r), resultFor(r, { done: 1 })]);
    const client = new WorkerClient(worker.io);
    const result = await client.request("hello", {});
    expect(result).toEqual({ done: 1 });
  });

  describe("progress", () => {
    function progressLine(id: string, ratio: number, etaMs: number | null) {
      return protocolLine({ id, type: "progress", stage: "s", ratio, etaMs });
    }

    test("hands the ratio to the callback", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.25, 3000),
        resultFor(r),
      ]);
      const client = new WorkerClient(worker.io);
      const ratios: number[] = [];
      await client.request(
        "separate",
        {},
        { onProgress: (p) => ratios.push(p.ratio) },
      );
      expect(ratios).toEqual([0.25]);
    });

    test("hands the eta to the callback", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.25, 3000),
        resultFor(r),
      ]);
      const client = new WorkerClient(worker.io);
      const etas: (number | null)[] = [];
      await client.request(
        "separate",
        {},
        { onProgress: (p) => etas.push(p.etaMs) },
      );
      expect(etas).toEqual([3000]);
    });

    test("does not call the callback for another request's progress", async () => {
      const worker = fakeWorker((r) => {
        if (r.method === "slow") return [];
        return [progressLine("1", 0.5, null), resultFor(r)];
      });
      const client = new WorkerClient(worker.io);
      const calls: number[] = [];
      void client.request("slow", {}).catch(() => {});
      await client.request(
        "fast",
        {},
        { onProgress: (p) => calls.push(p.ratio) },
      );
      expect(calls).toEqual([]);
    });

    test("still resolves a request without a callback", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.5, null),
        resultFor(r, { done: 1 }),
      ]);
      const client = new WorkerClient(worker.io);
      expect(await client.request("separate", {})).toEqual({ done: 1 });
    });

    test("still rejects progress for an unknown id", async () => {
      const worker = fakeWorker(() => [progressLine("99", 0, null)]);
      const client = new WorkerClient(worker.io);
      const outcome = client.request("hello", {}, { onProgress: () => {} });
      await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
    });

    test("rejects the request with the error a callback throws", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.5, null),
        resultFor(r),
      ]);
      const client = new WorkerClient(worker.io);
      const outcome = client.request(
        "separate",
        {},
        {
          onProgress: () => {
            throw new Error("terminal closed");
          },
        },
      );
      await expect(outcome).rejects.toThrow("terminal closed");
    });

    test("keeps working for later requests after a callback threw", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.5, null),
        resultFor(r, { n: r.id }),
      ]);
      const client = new WorkerClient(worker.io);
      await client
        .request(
          "separate",
          {},
          {
            onProgress: () => {
              throw new Error("terminal closed");
            },
          },
        )
        .catch(() => {});
      expect(await client.request("hello", {})).toEqual({ n: "2" });
    });

    test("stops calling a callback that threw", async () => {
      const worker = fakeWorker((r) => [
        progressLine(r.id, 0.1, null),
        progressLine(r.id, 0.2, null),
        resultFor(r),
      ]);
      const client = new WorkerClient(worker.io);
      let calls = 0;
      await client
        .request(
          "separate",
          {},
          {
            onProgress: () => {
              calls += 1;
              throw new Error("terminal closed");
            },
          },
        )
        .catch(() => {});
      expect(calls).toBe(1);
    });
  });

  test("reads a line split across chunks", async () => {
    const worker = fakeWorker((r) => {
      const whole = resultFor(r, { split: true });
      return [whole.slice(0, 7), whole.slice(7)];
    });
    const client = new WorkerClient(worker.io);
    const result = await client.request("hello", {});
    expect(result).toEqual({ split: true });
  });

  test("reads a character split across chunks", async () => {
    const worker = fakeWorker((r) => {
      const bytes = new TextEncoder().encode(resultFor(r, { text: "風" }));
      const inside = bytes.indexOf(0xe9) + 1;
      return [bytes.slice(0, inside), bytes.slice(inside)];
    });
    const client = new WorkerClient(worker.io);
    const result = await client.request("hello", {});
    expect(result).toEqual({ text: "風" });
  });

  test("reads CRLF line endings", async () => {
    const worker = fakeWorker((r) => [resultFor(r).replace("\n", "\r\n")]);
    const client = new WorkerClient(worker.io);
    const result = await client.request("hello", {});
    expect(result).toEqual({});
  });

  test("rejects with the worker's error code", async () => {
    const worker = fakeWorker((r) => [
      protocolLine({
        id: r.id,
        type: "error",
        code: "invalid_request",
        message: "bad",
      }),
    ]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("anchor", {});
    await expect(outcome).rejects.toMatchObject({ code: "invalid_request" });
  });

  test("rejects instead of throwing when the request cannot be written", async () => {
    const stdin = {
      write(): never {
        throw new Error("broken pipe");
      },
      flush() {},
      end() {},
    };
    const client = new WorkerClient({ stdin, stdout: new ReadableStream() });
    await expect(client.request("hello", {})).rejects.toThrow("broken pipe");
  });

  // Bun's pipe sink reports a broken pipe through the promise it returns, as
  // when the worker has already exited.
  test("rejects when writing the request fails asynchronously", async () => {
    const stdin = {
      write: () => Promise.reject(new Error("EPIPE")),
      flush() {},
      end() {},
    };
    const client = new WorkerClient({ stdin, stdout: new ReadableStream() });
    await expect(client.request("hello", {})).rejects.toThrow("EPIPE");
  });

  test("rejects when flushing the request fails asynchronously", async () => {
    const stdin = {
      write() {},
      flush: () => Promise.reject(new Error("EPIPE")),
      end() {},
    };
    const client = new WorkerClient({ stdin, stdout: new ReadableStream() });
    await expect(client.request("hello", {})).rejects.toThrow("EPIPE");
  });

  test("rejects a progress message for an id that was not asked", async () => {
    const worker = fakeWorker(() => [
      protocolLine({
        id: "99",
        type: "progress",
        stage: "asr",
        ratio: 0,
        etaMs: null,
      }),
    ]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("rejects pending requests on an error without an id", async () => {
    const worker = fakeWorker(() => [
      protocolLine({ id: null, type: "error", code: "internal", message: "" }),
    ]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    await expect(outcome).rejects.toBeInstanceOf(WorkerError);
  });

  test("rejects a prefixed line that is not JSON", async () => {
    const worker = fakeWorker(() => [`${PREFIX}{oops\n`]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("rejects a prefixed line that is not a response", async () => {
    const worker = fakeWorker((r) => [protocolLine({ id: r.id, type: "x" })]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("rejects when a response names an id that was not asked", async () => {
    const worker = fakeWorker(() => [
      protocolLine({ id: "99", type: "result", result: {} }),
    ]);
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("rejects pending requests when the worker's output ends", async () => {
    const worker = fakeWorker();
    const client = new WorkerClient(worker.io);
    const outcome = client.request("hello", {});
    worker.finish();
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("rejects requests made after the worker's output ended", async () => {
    const worker = fakeWorker();
    const client = new WorkerClient(worker.io);
    worker.finish();
    await client.done;
    await expect(client.request("hello", {})).rejects.toBeInstanceOf(
      WorkerProtocolError,
    );
  });

  test("close ends the worker's input", async () => {
    const worker = fakeWorker();
    const client = new WorkerClient(worker.io);
    await client.close();
    expect(worker.ended()).toBe(true);
  });
});

describe("handshake", () => {
  function helloWorker(hello: object) {
    return fakeWorker((r) => [resultFor(r, hello)]);
  }

  test("returns the worker's version", async () => {
    const worker = helloWorker({ protocol: 1, worker: "0.1.0", methods: [] });
    const client = new WorkerClient(worker.io);
    const result = await handshake(client, []);
    expect(result.worker).toBe("0.1.0");
  });

  test("rejects a worker that speaks another protocol", async () => {
    const worker = helloWorker({ protocol: 2, worker: "0.1.0", methods: [] });
    const client = new WorkerClient(worker.io);
    await expect(handshake(client, [])).rejects.toBeInstanceOf(
      WorkerProtocolError,
    );
  });

  test("rejects a worker that lacks a required method", async () => {
    const worker = helloWorker({
      protocol: 1,
      worker: "0",
      methods: ["hello"],
    });
    const client = new WorkerClient(worker.io);
    await expect(handshake(client, ["anchor"])).rejects.toThrow(
      "Worker 0 lacks methods: anchor",
    );
  });
});
