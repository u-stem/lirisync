import {
  copyFile,
  mkdir,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { splitLyricsLines } from "./src/labels";
import { assertNewSlug, decodeLyrics, mixFileName } from "./src/song-files";

const repoRoot = resolve(import.meta.dir, "..");

const USAGE =
  "usage: bun run eval:add-song <name> --audio <file> --lyrics <file> [--songs-dir <path>]";

async function existingSongs(songsDir: string): Promise<string[]> {
  const entries = await readdir(songsDir, { withFileTypes: true }).catch(
    (error: unknown) => {
      if (
        error instanceof Error &&
        "code" in error &&
        error.code === "ENOENT"
      ) {
        return [];
      }
      throw error;
    },
  );
  return entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
}

async function assertFile(path: string, what: string): Promise<void> {
  const info = await stat(path).catch(() => null);
  if (info === null || !info.isFile()) {
    throw new Error(`${what} ${path} is not a file`);
  }
}

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      audio: { type: "string" },
      lyrics: { type: "string" },
      "songs-dir": { type: "string" },
    },
    strict: true,
  });
  const [slug, ...extra] = positionals;
  const { audio, lyrics } = values;
  if (
    slug === undefined ||
    extra.length > 0 ||
    audio === undefined ||
    lyrics === undefined
  ) {
    throw new Error(USAGE);
  }
  const songsDir = resolve(
    values["songs-dir"] ?? join(repoRoot, "eval", "songs"),
  );

  // Check everything before creating the folder, so a failure leaves nothing.
  assertNewSlug(slug, await existingSongs(songsDir));
  await assertFile(audio, "audio");
  await assertFile(lyrics, "lyrics");
  const mix = mixFileName(audio);
  let lyricsText: string;
  try {
    lyricsText = decodeLyrics(await Bun.file(lyrics).bytes());
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${lyrics}: ${reason}`);
  }

  const songDir = join(songsDir, slug);
  await mkdir(songsDir, { recursive: true });
  // Not recursive: it fails when the folder exists, so the cleanup below only
  // ever removes a folder made here.
  await mkdir(songDir);
  try {
    await mkdir(join(songDir, "audio"));
    await copyFile(audio, join(songDir, "audio", mix));
    await writeFile(join(songDir, "lyrics.txt"), lyricsText, { flag: "wx" });
  } catch (error) {
    // The folder was made above, so nothing else is lost.
    await rm(songDir, { recursive: true, force: true });
    throw error;
  }

  const lines = splitLyricsLines(lyricsText);
  const sung = lines.filter((line) => line.trim() !== "").length;
  process.stderr.write(
    `Added ${songDir}\n  audio/${mix}\n  lyrics.txt (${lines.length} lines, ${sung} sung)\n` +
      `Next: label it (see "正解ラベルの付け方" in eval/README.md), then run bun run eval:all\n`,
  );
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
