import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import type { AsrWord } from "@lirisync/core";
import { parseAsrFile } from "./asr-file";
import {
  assertLabelsSung,
  parseAudacityLabels,
  splitLyricsLines,
  type TruthLine,
} from "./labels";

/** One evaluation song with everything stage 1 and scoring need. */
export type Song = {
  slug: string;
  /** `lyrics.txt` as written, for repeat detection. */
  lyricsText: string;
  /** One display line each, in order. */
  lyrics: string[];
  truth: TruthLine[];
  words: AsrWord[];
};

const ASR_NAME = /^[A-Za-z0-9._-]+$/;

/** Throws unless `asrName` is safe to use as a file name under `asr/`. */
export function assertAsrName(asrName: string): void {
  // The name becomes a path segment, so it must not be able to leave `asr/`.
  if (!ASR_NAME.test(asrName) || asrName === "." || asrName === "..") {
    throw new Error(
      `Invalid ASR name ${JSON.stringify(asrName)}: use letters, digits, ".", "_" and "-"`,
    );
  }
}

/** Slugs of the songs under `songsDir`, sorted. Throws when there are none. */
export async function listSongs(songsDir: string): Promise<string[]> {
  const entries = await readdir(songsDir, { withFileTypes: true });
  const slugs = entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  if (slugs.length === 0) {
    throw new Error(`No songs found in ${songsDir}`);
  }
  return slugs;
}

/**
 * Loads one song: `labels.txt`, `lyrics.txt` and `asr/<asrName>.json`. Every
 * failure is rethrown with the slug in front, so a bad file is easy to find
 * when many songs are loaded.
 */
export async function loadSong(
  songsDir: string,
  slug: string,
  asrName: string,
): Promise<Song> {
  assertAsrName(asrName);
  try {
    const dir = join(songsDir, slug);
    const [labelsText, lyricsText, asrText] = await Promise.all([
      readFile(join(dir, "labels.txt"), "utf8"),
      readFile(join(dir, "lyrics.txt"), "utf8"),
      readFile(join(dir, "asr", `${asrName}.json`), "utf8"),
    ]);
    const truth = parseAudacityLabels(labelsText);
    if (truth.length === 0) {
      throw new Error("labels.txt has no labels");
    }
    assertLabelsSung(truth, lyricsText);
    return {
      slug,
      lyricsText,
      lyrics: splitLyricsLines(lyricsText),
      truth,
      words: parseAsrFile(asrText),
    };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${slug}: ${reason}`);
  }
}
