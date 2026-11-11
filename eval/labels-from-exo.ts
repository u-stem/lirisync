import { writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { exoLabels, formatAudacityLabels, parseExo } from "./src/exo-labels";
import {
  assertLabelsSung,
  parseAudacityLabels,
  unlabeledLines,
} from "./src/labels";
import { listSongs, selectSongs } from "./src/song-set";

const repoRoot = resolve(import.meta.dir, "..");

const USAGE =
  "usage: bun run eval:labels <file.exo> --song <slug> [--songs-dir <path>] [--overwrite]";

/** ExEdit writes object files in Shift_JIS. */
function decodeShiftJis(bytes: Uint8Array, path: string): string {
  try {
    return new TextDecoder("shift_jis", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(
      `${path} is not Shift_JIS text; export it from ExEdit with "オブジェクトファイルのエクスポート"`,
    );
  }
}

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      song: { type: "string" },
      "songs-dir": { type: "string" },
      overwrite: { type: "boolean", default: false },
    },
    strict: true,
  });
  const [exoPath, ...extra] = positionals;
  if (exoPath === undefined || extra.length > 0 || values.song === undefined) {
    throw new Error(USAGE);
  }
  const songsDir = resolve(
    values["songs-dir"] ?? join(repoRoot, "eval", "songs"),
  );
  const [slug] = selectSongs(await listSongs(songsDir), [values.song]);
  if (slug === undefined) throw new Error(USAGE);
  const songDir = join(songsDir, slug);

  const exo = decodeShiftJis(await Bun.file(exoPath).bytes(), exoPath);
  const project = parseExo(exo);
  const labels = exoLabels(project);
  const lyrics = await Bun.file(join(songDir, "lyrics.txt"))
    .text()
    .catch(() => {
      throw new Error(
        `${slug}: lyrics.txt is missing; the labels are checked against it`,
      );
    });
  assertLabelsSung(labels, lyrics);

  const text = formatAudacityLabels(labels);
  // What `bun run eval` will read must give back the same labels.
  if (!Bun.deepEquals(parseAudacityLabels(text), labels)) {
    throw new Error("labels.txt would not read back as the same labels");
  }
  const out = join(songDir, "labels.txt");
  await writeFile(out, text, { flag: values.overwrite ? "w" : "wx" }).catch(
    (error: unknown) => {
      if (
        error instanceof Error &&
        "code" in error &&
        error.code === "EEXIST"
      ) {
        throw new Error(`${out} exists; pass --overwrite to replace it`);
      }
      throw error;
    },
  );

  const frameMs = (1000 * project.scale) / project.rate;
  process.stderr.write(
    `Wrote ${labels.length} labels to ${out} (1 frame = ${frameMs.toFixed(1)} ms)\n`,
  );
  const missing = unlabeledLines(labels, lyrics);
  if (missing.length > 0) {
    process.stderr.write(
      `Sung lines without a label (left out of the evaluation): ${missing.join(", ")}\n`,
    );
  }
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
