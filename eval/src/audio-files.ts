import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";

/** The stem `lirisync-transcribe` reads by default; also what we write. */
export const VOCALS_STEM = "vocals";

/** The stem of the song's mix, which separation reads by default. */
export const MIX_STEM = "mix";

/** Compared without case, as Windows file names are. */
export function sameName(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/**
 * The name without its last extension, like `Path.stem` in Python. A leading
 * or trailing dot does not start an extension, so `vocals.meta.json` has the
 * stem `vocals.meta`.
 */
export function stemOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 || dot === name.length - 1 ? name : name.slice(0, dot);
}

/** Names of the regular files in `audioDir`, sorted. Links are followed. */
export async function listFiles(audioDir: string): Promise<string[]> {
  let names: string[];
  try {
    names = await readdir(audioDir);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return [];
    }
    throw error;
  }
  const files: string[] = [];
  for (const name of names.sort()) {
    const info = await stat(join(audioDir, name)).catch(() => null);
    if (info?.isFile()) files.push(name);
  }
  return files;
}

/** The files whose stem is `stem`, ignoring case. */
export function withStem(files: readonly string[], stem: string): string[] {
  return files.filter((name) => sameName(stemOf(name), stem));
}

/**
 * The one file in `files` whose stem is `stem`. Throws when there is none or
 * more than one.
 */
export function pickByStem(files: readonly string[], stem: string): string {
  const found = withStem(files, stem);
  const [first] = found;
  if (first === undefined) {
    throw new Error(`no audio file audio/${stem}.*`);
  }
  if (found.length > 1) {
    throw new Error(`more than one audio/${stem}.* file: ${found.join(", ")}`);
  }
  return first;
}

/**
 * The absolute path of the song's vocals, `audio/vocals.*`: the file whose
 * name without its last extension is `vocals`, ignoring case. This is the
 * file `lirisync-transcribe` reads. Throws, with the slug in front, unless
 * there is exactly one.
 */
export async function findVocals(
  songsDir: string,
  slug: string,
): Promise<string> {
  const audioDir = join(songsDir, slug, "audio");
  try {
    const name = pickByStem(await listFiles(audioDir), VOCALS_STEM);
    return join(audioDir, name);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${slug}: ${reason}`);
  }
}
