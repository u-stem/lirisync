import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  assertNewSlug,
  checkSongFiles,
  decodeLyrics,
  listSongFiles,
  mixFileName,
} from "../src/song-files";

const READY = ["audio/mix.wav", "lyrics.txt", "labels.txt"];

describe("checkSongFiles", () => {
  test("finds nothing wrong with a complete song", () => {
    expect(checkSongFiles(READY)).toEqual([]);
  });

  test("accepts separated vocals in place of the mix", () => {
    const problems = checkSongFiles([
      "audio/vocals.wav",
      "lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([]);
  });

  test("compares the audio file name without case, as separation does", () => {
    const problems = checkSongFiles([
      "audio/MIX.WAV",
      "lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([]);
  });

  test("asks for the exact case of a text file, which is opened by name", () => {
    const problems = checkSongFiles([
      "audio/mix.wav",
      "Lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "lyrics.txt",
        blocking: false,
        hint: "found Lyrics.txt: rename it to lyrics.txt",
      },
    ]);
  });

  test("asks for the exact case of the audio folder", () => {
    const problems = checkSongFiles([
      "Audio/mix.wav",
      "lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "audio/mix.*",
        blocking: true,
        hint: "found the folder Audio: rename it to audio",
      },
    ]);
  });

  test("names the files in audio/ when there is no mix", () => {
    const problems = checkSongFiles([
      "audio/song title.wav",
      "lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "audio/mix.*",
        blocking: true,
        hint: 'audio/ has "song title.wav": rename the song\'s audio to mix.<extension>',
      },
    ]);
  });

  test("blocks a song with no audio at all", () => {
    const problems = checkSongFiles(["lyrics.txt", "labels.txt"]);
    expect(problems).toEqual([
      { file: "audio/mix.*", blocking: true, hint: null },
    ]);
  });

  test("blocks two mixes", () => {
    const problems = checkSongFiles([
      "audio/mix.wav",
      "audio/mix.mp3",
      "lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "audio/mix.*",
        blocking: true,
        hint: "more than one: mix.mp3, mix.wav; keep one",
      },
    ]);
  });

  test("points at a doubled extension", () => {
    const problems = checkSongFiles([
      "audio/mix.wav",
      "lyrics.txt.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "lyrics.txt",
        blocking: false,
        hint: "found lyrics.txt.txt: rename it to lyrics.txt",
      },
    ]);
  });

  test("points at a file in a subfolder", () => {
    const problems = checkSongFiles([
      "audio/mix.wav",
      "lyrics/lyrics.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "lyrics.txt",
        blocking: false,
        hint: "found lyrics/lyrics.txt: move it into the song folder itself as lyrics.txt",
      },
    ]);
  });

  test("points at a doubled extension in a subfolder", () => {
    const problems = checkSongFiles([
      "audio/mix.wav",
      "lyrics/lyrics.txt.txt",
      "labels.txt",
    ]);
    expect(problems).toEqual([
      {
        file: "lyrics.txt",
        blocking: false,
        hint: "found lyrics/lyrics.txt.txt: move it into the song folder itself as lyrics.txt",
      },
    ]);
  });

  test("reports missing labels without blocking", () => {
    const problems = checkSongFiles(["audio/mix.wav", "lyrics.txt"]);
    expect(problems).toEqual([
      { file: "labels.txt", blocking: false, hint: null },
    ]);
  });
});

describe("assertNewSlug", () => {
  test("accepts letters, digits, dot, underscore and hyphen", () => {
    expect(() => assertNewSlug("song-02_a.b", [])).not.toThrow();
  });

  test("rejects a slug starting with a dot", () => {
    expect(() => assertNewSlug(".hidden", [])).toThrow("Invalid song name");
  });

  test("rejects a path", () => {
    expect(() => assertNewSlug("a/b", [])).toThrow("Invalid song name");
  });

  test("rejects a slug ending with a dot, which Windows drops", () => {
    expect(() => assertNewSlug("song01.", [])).toThrow("Invalid song name");
  });

  test("rejects a slug that exists, without case", () => {
    expect(() => assertNewSlug("Song01", ["song01"])).toThrow("already exists");
  });
});

describe("mixFileName", () => {
  test("keeps the extension in lower case", () => {
    expect(mixFileName("C:\\music\\曲名.WAV")).toBe("mix.wav");
  });

  test("rejects a file without an extension", () => {
    expect(() => mixFileName("/music/track")).toThrow("no extension");
  });
});

describe("decodeLyrics", () => {
  test("reads UTF-8", () => {
    const bytes = new TextEncoder().encode("風が吹く\n");
    expect(decodeLyrics(bytes)).toBe("風が吹く\n");
  });

  test("drops a byte order mark", () => {
    const bytes = new TextEncoder().encode("\uFEFF風\n");
    expect(decodeLyrics(bytes)).toBe("風\n");
  });

  test("rejects text that is not UTF-8", () => {
    // "風" in Shift_JIS.
    const bytes = new Uint8Array([0x95, 0x97, 0x0a]);
    expect(() => decodeLyrics(bytes)).toThrow("not UTF-8");
  });
});

describe("listSongFiles", () => {
  test("follows a symbolic link to a file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "song-files-"));
    try {
      await mkdir(join(dir, "audio"));
      await writeFile(join(dir, "real.wav"), "");
      await symlink(join(dir, "real.wav"), join(dir, "audio", "mix.wav"));
      expect(await listSongFiles(dir)).toEqual(["audio/mix.wav", "real.wav"]);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  test("lists nested files with slashes, sorted", async () => {
    const dir = await mkdtemp(join(tmpdir(), "song-files-"));
    try {
      await mkdir(join(dir, "audio"));
      await mkdir(join(dir, "lyrics"));
      await writeFile(join(dir, "labels.txt"), "");
      await writeFile(join(dir, "audio", "mix.wav"), "");
      await writeFile(join(dir, "lyrics", "lyrics.txt"), "");
      expect(await listSongFiles(dir)).toEqual([
        "audio/mix.wav",
        "labels.txt",
        "lyrics/lyrics.txt",
      ]);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
