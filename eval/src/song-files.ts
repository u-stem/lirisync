import { readdir } from "node:fs/promises";
import { extname } from "node:path";
import { sameName, stemOf, VOCALS_STEM, withStem } from "./audio-files";

export const MIX_STEM = "mix";

/** A file a song lacks, and what was found that may be meant for it. */
export type SongFileProblem = {
  file: string;
  /** True when separation cannot run; otherwise only the eval steps stop. */
  blocking: boolean;
  hint: string | null;
};

function baseName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

function directoryOf(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "" : path.slice(0, slash);
}

function audioProblem(files: readonly string[]): SongFileProblem | null {
  const audio = files
    .filter((path) => directoryOf(path).toLowerCase() === "audio")
    .map(baseName);
  // Separation is skipped once the vocals exist, so the mix is not needed.
  if (withStem(audio, VOCALS_STEM).length > 0) return null;
  const mixes = withStem(audio, MIX_STEM);
  if (mixes.length === 1) return null;
  const file = `audio/${MIX_STEM}.*`;
  if (mixes.length > 1) {
    return {
      file,
      blocking: true,
      hint: `more than one: ${[...mixes].sort().join(", ")}; keep one`,
    };
  }
  const others = audio.filter((name) => !stemOf(name).endsWith(".meta"));
  if (others.length === 0) return { file, blocking: true, hint: null };
  const listed = others.map((name) => JSON.stringify(name)).join(", ");
  return {
    file,
    blocking: true,
    hint: `audio/ has ${listed}: rename the song's audio to ${MIX_STEM}.<extension>`,
  };
}

/**
 * A file that is probably `name` put in the wrong place or saved with a
 * doubled extension: same name in a subfolder, or `name` followed by more.
 */
function lookalike(files: readonly string[], name: string): string | undefined {
  const lower = name.toLowerCase();
  return files.find((path) => {
    const base = baseName(path).toLowerCase();
    return base === lower || base.startsWith(`${lower}.`);
  });
}

function textProblem(
  files: readonly string[],
  name: string,
): SongFileProblem | null {
  if (files.some((path) => sameName(path, name))) return null;
  const found = lookalike(files, name);
  let hint: string | null = null;
  if (found !== undefined) {
    hint = found.includes("/")
      ? `found ${found}: move it into the song folder itself`
      : `found ${found}: rename it to ${name}`;
  }
  return { file: name, blocking: false, hint };
}

/**
 * What a song folder lacks for `eval:all`. `files` are the paths of the files
 * in it, relative and with `/` separators.
 */
export function checkSongFiles(files: readonly string[]): SongFileProblem[] {
  return [
    audioProblem(files),
    textProblem(files, "lyrics.txt"),
    textProblem(files, "labels.txt"),
  ].filter((problem) => problem !== null);
}

/** The files under `dir`, relative and with `/` separators, as `checkSongFiles` takes them. */
export async function listSongFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { recursive: true, withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => {
      const relative = entry.parentPath
        .slice(dir.length)
        .replace(/^[\\/]+/, "");
      const path = relative === "" ? entry.name : `${relative}/${entry.name}`;
      return path.replaceAll("\\", "/");
    })
    .sort();
}

const SLUG = /^[A-Za-z0-9_-][A-Za-z0-9._-]*$/;

/** Throws unless `slug` is a usable new song folder name among `existing`. */
export function assertNewSlug(slug: string, existing: readonly string[]): void {
  if (!SLUG.test(slug)) {
    throw new Error(
      `Invalid song name ${JSON.stringify(slug)}: use letters, digits, ".", "_" and "-", not starting with "."`,
    );
  }
  if (existing.some((name) => sameName(name, slug))) {
    throw new Error(`Song ${JSON.stringify(slug)} already exists`);
  }
}

/** `mix` with the extension of `audioPath`, in lower case. */
export function mixFileName(audioPath: string): string {
  const extension = extname(audioPath.replaceAll("\\", "/")).toLowerCase();
  if (extension === "" || extension === ".") {
    throw new Error(
      `${audioPath} has no extension; the format is read from it`,
    );
  }
  return `${MIX_STEM}${extension}`;
}

/** Lyrics bytes as text: UTF-8, without a byte order mark. */
export function decodeLyrics(bytes: Uint8Array): string {
  try {
    // The decoder drops a leading byte order mark by default.
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(
      "the lyrics are not UTF-8; save them as UTF-8 and try again",
    );
  }
}
