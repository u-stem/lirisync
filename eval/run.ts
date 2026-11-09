import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import type { AnchoredLine } from "@lirisync/core";
import { WorkerAnchorer } from "./adapters/worker-anchorer";
import { startWorker } from "./adapters/worker-process";
import { assertLabeledLinesSung, toPredictions } from "./src/predictions";
import { buildReport, formatReport, type SongResult } from "./src/report";
import { assertAsrName, listSongs, loadSong, type Song } from "./src/song-set";

const repoRoot = resolve(import.meta.dir, "..");

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      asr: { type: "string" },
      "songs-dir": {
        type: "string",
        default: join(repoRoot, "eval", "songs"),
      },
      song: { type: "string", multiple: true },
      out: { type: "string" },
    },
    strict: true,
  });
  const asr = values.asr;
  if (asr === undefined) {
    throw new Error("--asr <name> is required");
  }
  assertAsrName(asr);
  const songsDir = resolve(values["songs-dir"]);
  const available = await listSongs(songsDir);
  const wanted = values.song ?? available;
  for (const slug of wanted) {
    if (!available.includes(slug)) {
      throw new Error(`Unknown song ${JSON.stringify(slug)}`);
    }
  }
  const slugs = available.filter((slug) => wanted.includes(slug));

  // Load everything before starting the worker, so a bad file fails fast.
  const songs: Song[] = [];
  for (const slug of slugs) {
    songs.push(await loadSong(songsDir, slug, asr));
  }

  const worker = await startWorker(
    [
      "uv",
      "--directory",
      join(repoRoot, "workers", "align"),
      "run",
      "lirisync-worker",
    ],
    ["anchor"],
  );
  const results: SongResult[] = [];
  try {
    const anchorer = new WorkerAnchorer(worker.client);
    for (const song of songs) {
      let lines: AnchoredLine[];
      try {
        lines = await anchorer.anchor({
          lyrics: song.lyrics,
          words: song.words,
          ignored: [],
        });
        assertLabeledLinesSung(song.truth, lines);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        throw new Error(`${song.slug}: ${reason}`);
      }
      results.push({
        slug: song.slug,
        lyricsText: song.lyricsText,
        truth: song.truth,
        predictions: toPredictions(lines),
      });
    }
  } finally {
    const exitCode = await worker.stop();
    if (exitCode !== 0) {
      process.stderr.write(
        `warning: the worker exited with code ${exitCode}\n`,
      );
      process.exitCode = 1;
    }
  }

  const report = buildReport(results);
  process.stdout.write(formatReport(report));
  if (values.out !== undefined) {
    const out = resolve(values.out);
    await mkdir(dirname(out), { recursive: true });
    const json = { asr, worker: worker.hello.worker, report };
    await writeFile(out, `${JSON.stringify(json, null, 2)}\n`);
  }
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
