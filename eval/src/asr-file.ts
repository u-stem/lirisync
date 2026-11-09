import { type AsrWord, parseMs } from "@lirisync/core";
import { z } from "zod";

const AsrFile = z.strictObject({
  words: z.array(
    z.strictObject({
      startMs: z.number().int().nonnegative(),
      endMs: z.number().int().nonnegative(),
      text: z.string(),
    }),
  ),
});

/**
 * Parses an ASR transcript file: `{ "words": [{ "startMs", "endMs", "text" }] }`,
 * the worker protocol's word shape. The worker would reject a word that ends
 * before it starts or words out of order too, but this file is where the fault
 * is, so the error names the 1-based word.
 */
export function parseAsrFile(text: string): AsrWord[] {
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`The ASR file is not valid JSON: ${reason}`);
  }
  const parsed = AsrFile.safeParse(json);
  if (!parsed.success) {
    throw new Error(`The ASR file is not usable: ${parsed.error.message}`);
  }
  const words: AsrWord[] = [];
  parsed.data.words.forEach((word, index) => {
    const where = `word ${index + 1}`;
    if (word.endMs < word.startMs) {
      throw new Error(`${where}: ends before it starts`);
    }
    const previous = words.at(-1);
    if (previous !== undefined && word.startMs < previous.start) {
      throw new Error(`${where}: starts before word ${index}`);
    }
    words.push({
      start: parseMs(word.startMs),
      end: parseMs(word.endMs),
      text: word.text,
    });
  });
  return words;
}
