import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { parseAsrFile } from "../src/asr-file";

function file(words: object[]): string {
  return JSON.stringify({ words });
}

describe("parseAsrFile", () => {
  test("reads words as Ms", () => {
    const text = file([{ startMs: 1000, endMs: 1800, text: "風が吹く" }]);
    const result = parseAsrFile(text);
    expect(result).toEqual([
      { start: parseMs(1000), end: parseMs(1800), text: "風が吹く" },
    ]);
  });

  test("accepts an empty word list", () => {
    const result = parseAsrFile(file([]));
    expect(result).toEqual([]);
  });

  test("accepts overlapping words with equal starts", () => {
    const text = file([
      { startMs: 1000, endMs: 2000, text: "a" },
      { startMs: 1000, endMs: 1500, text: "b" },
    ]);
    expect(parseAsrFile(text)).toHaveLength(2);
  });

  test("rejects text that is not JSON", () => {
    expect(() => parseAsrFile("{")).toThrow("not valid JSON");
  });

  test("rejects a missing words array", () => {
    expect(() => parseAsrFile("{}")).toThrow("words");
  });

  test("rejects an unknown field", () => {
    const text = JSON.stringify({ words: [], extra: 1 });
    expect(() => parseAsrFile(text)).toThrow("Unrecognized key");
  });

  test("rejects a fractional time", () => {
    const text = file([{ startMs: 1.5, endMs: 2, text: "a" }]);
    expect(() => parseAsrFile(text)).toThrow("expected int");
  });

  test("rejects a negative time", () => {
    const text = file([{ startMs: -1, endMs: 2, text: "a" }]);
    expect(() => parseAsrFile(text)).toThrow("expected number to be >=0");
  });

  test("names the word that ends before it starts", () => {
    const text = file([
      { startMs: 0, endMs: 10, text: "a" },
      { startMs: 50, endMs: 40, text: "b" },
    ]);
    expect(() => parseAsrFile(text)).toThrow("word 2: ends before it starts");
  });

  test("names the word that starts before the previous one", () => {
    const text = file([
      { startMs: 50, endMs: 60, text: "a" },
      { startMs: 40, endMs: 70, text: "b" },
    ]);
    expect(() => parseAsrFile(text)).toThrow("word 2: starts before word 1");
  });
});
