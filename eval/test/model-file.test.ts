import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assertModelFile, sha256File } from "../src/model-file";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "lirisync-model-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe("assertModelFile", () => {
  test("accepts a regular file", async () => {
    const path = join(dir, "m.onnx");
    await writeFile(path, "x");
    await expect(assertModelFile(path)).resolves.toBeUndefined();
  });

  test("rejects a missing file", async () => {
    await expect(assertModelFile(join(dir, "m.onnx"))).rejects.toThrow(
      "does not exist",
    );
  });

  test("rejects a directory", async () => {
    await mkdir(join(dir, "m.onnx"));
    await expect(assertModelFile(join(dir, "m.onnx"))).rejects.toThrow(
      "is not a file",
    );
  });
});

describe("sha256File", () => {
  test("hashes the content", async () => {
    const path = join(dir, "m.onnx");
    await writeFile(path, "abc");
    expect(await sha256File(path)).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  test("hashes an empty file", async () => {
    const path = join(dir, "m.onnx");
    await writeFile(path, "");
    expect(await sha256File(path)).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });
});
