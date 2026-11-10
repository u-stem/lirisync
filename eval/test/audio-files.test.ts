import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findVocals } from "../src/audio-files";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "lirisync-audio-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

async function addAudio(slug: string, ...names: string[]): Promise<void> {
  await mkdir(join(dir, slug, "audio"), { recursive: true });
  for (const name of names) {
    await writeFile(join(dir, slug, "audio", name), "x");
  }
}

describe("findVocals", () => {
  test("returns the path of the vocals file", async () => {
    await addAudio("a", "vocals.wav", "mix.mp3");
    expect(await findVocals(dir, "a")).toBe(
      join(dir, "a", "audio", "vocals.wav"),
    );
  });

  test("accepts any extension", async () => {
    await addAudio("a", "vocals.flac");
    expect(await findVocals(dir, "a")).toBe(
      join(dir, "a", "audio", "vocals.flac"),
    );
  });

  test("ignores case in the name", async () => {
    await addAudio("a", "Vocals.WAV");
    expect(await findVocals(dir, "a")).toBe(
      join(dir, "a", "audio", "Vocals.WAV"),
    );
  });

  test("does not take the metadata file for the vocals", async () => {
    await addAudio("a", "vocals.wav", "vocals.meta.json");
    expect(await findVocals(dir, "a")).toBe(
      join(dir, "a", "audio", "vocals.wav"),
    );
  });

  test("names the slug when there is no audio directory", async () => {
    await mkdir(join(dir, "a"));
    await expect(findVocals(dir, "a")).rejects.toThrow(
      "a: no audio file audio/vocals.*",
    );
  });

  test("rejects a directory without vocals", async () => {
    await addAudio("a", "mix.wav");
    await expect(findVocals(dir, "a")).rejects.toThrow(
      "no audio file audio/vocals.*",
    );
  });

  test("rejects two vocals files", async () => {
    await addAudio("a", "vocals.wav", "vocals.mp3");
    await expect(findVocals(dir, "a")).rejects.toThrow(
      "more than one audio/vocals.* file",
    );
  });
});
