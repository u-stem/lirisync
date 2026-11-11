/** Reads `stream` to its end, giving each chunk to every sink in order. */
export async function teeStream(
  stream: ReadableStream<Uint8Array>,
  sinks: readonly ((chunk: Uint8Array) => void)[],
): Promise<void> {
  for await (const chunk of stream) {
    for (const sink of sinks) sink(chunk);
  }
}
