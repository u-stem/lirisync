import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import type { AnchoredLine } from "@lirisync/core";
import { WorkerAnchorer } from "./adapters/worker-anchorer";
import { alignWorkerCommand, startWorker } from "./adapters/worker-process";
import {
  buildPerturbationReport,
  formatPerturbationReport,
  type PerturbationReport,
  runSongPerturbations,
  type SongPerturbations,
} from "./src/perturbation-run";
import { perturbations } from "./src/perturbations";
import { assertLabeledLinesSung, toPredictions } from "./src/predictions";
import { buildReport, formatReport, type SongResult } from "./src/report";
import {
  assertAsrName,
  listSongs,
  loadSong,
  type Song,
  selectSongs,
} from "./src/song-set";

const repoRoot = resolve(import.meta.dir, "..");

/**
 * Runs stage 1 on every perturbation of every song and compares each with the
 * baseline in `results`. Progress goes to stderr, one line per song.
 */
async function runPerturbations(
  anchorer: WorkerAnchorer,
  songs: readonly Song[],
  results: readonly SongResult[],
): Promise<PerturbationReport> {
  const plans = songs.map((song) => perturbations(song.lyrics, song.truth));
  const total = plans.reduce((sum, plan) => sum + plan.length, 0);
  process.stderr.write(`${total} perturbations\n`);
  const bySong: SongPerturbations[] = [];
  let done = 0;
  for (const [index, song] of songs.entries()) {
    const plan = plans[index];
    const baseline = results[index];
    if (plan === undefined || baseline === undefined) {
      throw new Error(`${song.slug}: no baseline for the perturbation run`);
    }
    const started = performance.now();
    const records = await runSongPerturbations(
      anchorer,
      song,
      baseline.predictions,
      plan,
    );
    done += records.length;
    const seconds = (performance.now() - started) / 1000;
    const perCall = records.length === 0 ? 0 : seconds / records.length;
    process.stderr.write(
      `[${index + 1}/${songs.length}] ${song.slug}: ${records.length} perturbations ` +
        `in ${seconds.toFixed(1)} s (${perCall.toFixed(2)} s each), ${done}/${total} done\n`,
    );
    bySong.push({ slug: song.slug, perturbations: records });
  }
  return buildPerturbationReport(bySong);
}

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
      perturb: { type: "boolean", default: false },
    },
    strict: true,
  });
  const asr = values.asr;
  if (asr === undefined) {
    throw new Error("--asr <name> is required");
  }
  assertAsrName(asr);
  const songsDir = resolve(values["songs-dir"]);
  const slugs = selectSongs(await listSongs(songsDir), values.song);

  // Load everything before starting the worker, so a bad file fails fast.
  const songs: Song[] = [];
  for (const slug of slugs) {
    songs.push(await loadSong(songsDir, slug, asr));
  }

  const worker = await startWorker(alignWorkerCommand(repoRoot), ["anchor"]);
  const results: SongResult[] = [];
  let perturbation: PerturbationReport | undefined;
  let perturbationFailure: { error: unknown } | undefined;
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
    if (values.perturb) {
      // A failed perturbation must not cost the baseline report, which is
      // already computed: it is printed first and the failure rethrown below.
      try {
        perturbation = await runPerturbations(anchorer, songs, results);
      } catch (error) {
        perturbationFailure = { error };
      }
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
  if (perturbation !== undefined) {
    process.stdout.write(`\n${formatPerturbationReport(perturbation)}`);
  }
  if (values.out !== undefined) {
    const out = resolve(values.out);
    await mkdir(dirname(out), { recursive: true });
    const json = {
      asr,
      worker: worker.hello.worker,
      report,
      ...(perturbation === undefined ? {} : { perturbation }),
    };
    await writeFile(out, `${JSON.stringify(json, null, 2)}\n`);
  }
  if (perturbationFailure !== undefined) {
    throw perturbationFailure.error;
  }
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
