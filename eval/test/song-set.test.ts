import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseMs } from "@lirisync/core";
import { assertAsrName, listSongs, loadSong } from "../src/song-set";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "lirisync-songs-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

type Files = { labels?: string; lyrics?: string; asr?: string };

async function addSong(slug: string, files: Files = {}): Promise<void> {
  const {
    labels = "1.0\t1.0\t1\n",
    lyrics = "first\nsecond\n",
    asr = JSON.stringify({ words: [{ startMs: 900, endMs: 1500, text: "x" }] }),
  } = files;
  await mkdir(join(dir, slug, "asr"), { recursive: true });
  await writeFile(join(dir, slug, "labels.txt"), labels);
  await writeFile(join(dir, slug, "lyrics.txt"), lyrics);
  await writeFile(join(dir, slug, "asr", "demo.json"), asr);
}

describe("listSongs", () => {
  test("returns subdirectory names in sorted order", async () => {
    await addSong("b");
    await addSong("a");
    expect(await listSongs(dir)).toEqual(["a", "b"]);
  });

  test("ignores plain files", async () => {
    await addSong("a");
    await writeFile(join(dir, "notes.txt"), "x");
    expect(await listSongs(dir)).toEqual(["a"]);
  });

  test("ignores directories whose name starts with a dot", async () => {
    await addSong("a");
    await mkdir(join(dir, ".cache"));
    expect(await listSongs(dir)).toEqual(["a"]);
  });

  test("rejects a directory with no songs", async () => {
    await expect(listSongs(dir)).rejects.toThrow("No songs");
  });

  test("rejects a missing directory", async () => {
    await expect(listSongs(join(dir, "missing"))).rejects.toThrow();
  });
});

describe("loadSong", () => {
  test("splits the lyrics into lines", async () => {
    await addSong("a");
    const song = await loadSong(dir, "a", "demo");
    expect(song.lyrics).toEqual(["first", "second"]);
  });

  test("keeps the lyrics text for repeat detection", async () => {
    await addSong("a");
    const song = await loadSong(dir, "a", "demo");
    expect(song.lyricsText).toBe("first\nsecond\n");
  });

  test("reads the labels as truth", async () => {
    await addSong("a");
    const song = await loadSong(dir, "a", "demo");
    expect(song.truth).toEqual([{ line: 1, start: parseMs(1000) }]);
  });

  test("reads the ASR words of the named transcript", async () => {
    await addSong("a");
    const song = await loadSong(dir, "a", "demo");
    expect(song.words).toEqual([
      { start: parseMs(900), end: parseMs(1500), text: "x" },
    ]);
  });

  test("names the song when a file is missing", async () => {
    await addSong("a");
    await expect(loadSong(dir, "a", "other")).rejects.toThrow(/^a: /);
  });

  test("names the song when the labels do not fit the lyrics", async () => {
    await addSong("a", { labels: "1.0\t1.0\t9\n" });
    await expect(loadSong(dir, "a", "demo")).rejects.toThrow(
      /^a: .*past the end/,
    );
  });

  test("names the song when the ASR file is invalid", async () => {
    await addSong("a", { asr: "{" });
    await expect(loadSong(dir, "a", "demo")).rejects.toThrow(
      /^a: .*not valid JSON/,
    );
  });

  test("rejects a song whose labels file has no labels", async () => {
    await addSong("a", { labels: "\n" });
    await expect(loadSong(dir, "a", "demo")).rejects.toThrow(
      "a: labels.txt has no labels",
    );
  });

  test("keeps blank lyric lines so indices match label line numbers", async () => {
    await addSong("a", { lyrics: "first\n\nthird\n", labels: "3.0\t3.0\t3\n" });
    const song = await loadSong(dir, "a", "demo");
    expect(song.lyrics).toEqual(["first", "", "third"]);
  });

  test("rejects an ASR name with a path separator", async () => {
    await addSong("a");
    await expect(loadSong(dir, "a", "../demo")).rejects.toThrow("ASR name");
  });

  test("rejects the ASR name ..", async () => {
    await addSong("a");
    await expect(loadSong(dir, "a", "..")).rejects.toThrow("ASR name");
  });
});

describe("assertAsrName", () => {
  test("accepts letters, digits, dot, underscore and hyphen", () => {
    expect(() => assertAsrName("whisper-large_v3.1")).not.toThrow();
  });

  test("rejects an empty name", () => {
    expect(() => assertAsrName("")).toThrow("ASR name");
  });
});
