import { describe, expect, test } from "bun:test";
import { teeStream } from "../src/tee";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

function collector(): {
  sink: (chunk: Uint8Array) => void;
  text: () => string;
} {
  const decoder = new TextDecoder();
  let text = "";
  return {
    sink: (chunk) => {
      text += decoder.decode(chunk, { stream: true });
    },
    text: () => text + decoder.decode(),
  };
}

describe("teeStream", () => {
  test("gives every chunk to the first sink", async () => {
    const first = collector();
    const second = collector();
    await teeStream(streamOf("a\n", "b"), [first.sink, second.sink]);
    expect(first.text()).toBe("a\nb");
  });

  test("gives every chunk to the second sink", async () => {
    const first = collector();
    const second = collector();
    await teeStream(streamOf("a\n", "b"), [first.sink, second.sink]);
    expect(second.text()).toBe("a\nb");
  });

  test("keeps a character split across chunks", async () => {
    const bytes = new TextEncoder().encode("曲");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 1));
        controller.enqueue(bytes.slice(1));
        controller.close();
      },
    });
    const out = collector();
    await teeStream(stream, [out.sink]);
    expect(out.text()).toBe("曲");
  });
});
