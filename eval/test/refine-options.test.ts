import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parseMs } from "@lirisync/core";
import {
  assertAlignerModelDir,
  parseRefineOptions,
} from "../src/refine-options";

describe("parseRefineOptions", () => {
  test("is null without --refine", () => {
    expect(parseRefineOptions({})).toBeNull();
  });

  test("defaults to surface spelling", () => {
    expect(parseRefineOptions({ refine: "m" })?.spelling).toBe("surface");
  });

  test("defaults to a margin of 1000 ms", () => {
    expect(parseRefineOptions({ refine: "m" })?.margin).toBe(parseMs(1000));
  });

  test("resolves the model directory", () => {
    // resolve() gives D:\m on Windows, so the expectation is resolved too.
    expect(parseRefineOptions({ refine: "/a/../m" })?.modelDir).toBe(
      resolve("/m"),
    );
  });

  test("takes the kana spelling", () => {
    const options = parseRefineOptions({ refine: "m", spelling: "kana" });
    expect(options?.spelling).toBe("kana");
  });

  test("takes a margin", () => {
    const options = parseRefineOptions({ refine: "m", "margin-ms": "250" });
    expect(options?.margin).toBe(parseMs(250));
  });

  test("takes a margin of 0", () => {
    const options = parseRefineOptions({ refine: "m", "margin-ms": "0" });
    expect(options?.margin).toBe(parseMs(0));
  });

  test("rejects an unknown spelling", () => {
    expect(() =>
      parseRefineOptions({ refine: "m", spelling: "romaji" }),
    ).toThrow("--spelling");
  });

  test.each([
    "-1",
    "1.5",
    "abc",
    "",
    " 5",
    "1e3",
    "0x10",
    "99999999999999999999",
  ])("rejects the margin %p", (margin) => {
    expect(() =>
      parseRefineOptions({ refine: "m", "margin-ms": margin }),
    ).toThrow("--margin-ms");
  });

  test("rejects --spelling without --refine", () => {
    expect(() => parseRefineOptions({ spelling: "kana" })).toThrow(
      "--spelling needs --refine",
    );
  });

  test("rejects --margin-ms without --refine", () => {
    expect(() => parseRefineOptions({ "margin-ms": "5" })).toThrow(
      "--margin-ms needs --refine",
    );
  });

  test("rejects an empty --refine", () => {
    expect(() => parseRefineOptions({ refine: "" })).toThrow("--refine");
  });
});

describe("assertAlignerModelDir", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "lirisync-aligner-"));
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  test("accepts a directory with both files", async () => {
    await writeFile(join(dir, "model.int8.onnx"), "x");
    await writeFile(join(dir, "vocab.json"), "{}");
    await expect(assertAlignerModelDir(dir)).resolves.toBeUndefined();
  });

  test("rejects a directory without the model", async () => {
    await writeFile(join(dir, "vocab.json"), "{}");
    await expect(assertAlignerModelDir(dir)).rejects.toThrow("model.int8.onnx");
  });

  test("rejects a directory without the vocabulary", async () => {
    await writeFile(join(dir, "model.int8.onnx"), "x");
    await expect(assertAlignerModelDir(dir)).rejects.toThrow("vocab.json");
  });

  test("rejects a directory that does not exist", async () => {
    await expect(assertAlignerModelDir(join(dir, "none"))).rejects.toThrow(
      "does not exist",
    );
  });

  test("rejects a model that is a directory", async () => {
    await mkdir(join(dir, "model.int8.onnx"));
    await writeFile(join(dir, "vocab.json"), "{}");
    await expect(assertAlignerModelDir(dir)).rejects.toThrow("not a file");
  });
});
