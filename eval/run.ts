import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import type { AnchoredLine, RefinedLine, Refiner } from "@lirisync/core";
import { WorkerAnchorer } from "./adapters/worker-anchorer";
import { alignWorkerCommand, startWorker } from "./adapters/worker-process";
import { WorkerRefiner } from "./adapters/worker-refiner";
import { findVocals } from "./src/audio-files";
import { MemoRefiner } from "./src/memo-refiner";
import {
  buildPerturbationReport,
  formatPerturbationReport,
  type PerturbationReport,
  runSongPerturbations,
  type SongPerturbations,
  stagePredictor,
} from "./src/perturbation-run";
import { perturbations } from "./src/perturbations";
import { assertLabeledLinesSung, toPredictions } from "./src/predictions";
import {
  assertAlignerModelDir,
  parseRefineOptions,
  type RefineOptions,
} from "./src/refine-options";
import {
  addStatusCounts,
  countStatuses,
  formatStatusCounts,
  type StatusCounts,
  toRefinedPredictions,
  windowsFromAnchors,
} from "./src/refinement";
import {
  buildReport,
  formatReport,
  type Report,
  type SongResult,
} from "./src/report";
import {
  assertAsrName,
  listSongs,
  loadSong,
  type Song,
  selectSongs,
} from "./src/song-set";
import {
  formatStageTwoVerdict,
  type StageTwoVerdict,
  stageTwoVerdict,
} from "./src/stage-verdict";

const repoRoot = resolve(import.meta.dir, "..");

/** What `--refine` gives the perturbation run: the refiner and the baselines. */
type PerturbRefine = {
  refiner: Refiner;
  options: RefineOptions;
  vocals: ReadonlyMap<string, string>;
  refinements: readonly SongRefinement[];
};

/** `refine` is `null` when stage 2 is not measured. */
type PerturbationReports = {
  anchor: PerturbationReport;
  refine: PerturbationReport | null;
};

/**
 * Runs stage 1, and stage 2 when `refine` is given, on every perturbation of
 * every song and compares each with the baseline in `results` (and in
 * `refine.refinements`). Progress goes to stderr, one line per song.
 */
async function runPerturbations(
  anchorer: WorkerAnchorer,
  refine: PerturbRefine | null,
  songs: readonly Song[],
  results: readonly SongResult[],
): Promise<PerturbationReports> {
  const plans = songs.map((song) => perturbations(song.lyrics, song.truth));
  const total = plans.reduce((sum, plan) => sum + plan.length, 0);
  process.stderr.write(`${total} perturbations\n`);
  const anchorSongs: SongPerturbations[] = [];
  const refineSongs: SongPerturbations[] = [];
  let done = 0;
  for (const [index, song] of songs.entries()) {
    const plan = plans[index];
    const baseline = results[index];
    if (plan === undefined || baseline === undefined) {
      throw new Error(`${song.slug}: no baseline for the perturbation run`);
    }
    let refineBaseline: SongRefinement | undefined;
    let audioPath: string | undefined;
    if (refine !== null) {
      refineBaseline = refine.refinements[index];
      audioPath = refine.vocals.get(song.slug);
      if (refineBaseline === undefined || audioPath === undefined) {
        throw new Error(
          `${song.slug}: no stage-2 baseline for the perturbation run`,
        );
      }
    }
    const predict = stagePredictor(
      anchorer,
      song.words,
      refine === null || audioPath === undefined
        ? null
        : {
            refiner: refine.refiner,
            request: {
              audioPath,
              modelDir: refine.options.modelDir,
              spelling: refine.options.spelling,
              ignored: [],
              margin: refine.options.margin,
            },
          },
    );
    const started = performance.now();
    const records = await runSongPerturbations(
      predict,
      song,
      {
        anchor: baseline.predictions,
        refine: refineBaseline?.result.predictions ?? null,
      },
      plan,
    );
    done += records.anchor.length;
    const seconds = (performance.now() - started) / 1000;
    const perCall =
      records.anchor.length === 0 ? 0 : seconds / records.anchor.length;
    process.stderr.write(
      `[${index + 1}/${songs.length}] ${song.slug}: ${records.anchor.length} perturbations ` +
        `in ${seconds.toFixed(1)} s (${perCall.toFixed(2)} s each), ${done}/${total} done\n`,
    );
    anchorSongs.push({ slug: song.slug, perturbations: records.anchor });
    if (records.refine !== null) {
      refineSongs.push({ slug: song.slug, perturbations: records.refine });
    }
  }
  return {
    anchor: buildPerturbationReport(anchorSongs),
    refine: refine === null ? null : buildPerturbationReport(refineSongs),
  };
}

/** The `refine` entry of the `--out` file. Lyrics text is not included. */
type RefineJson = {
  spelling: RefineOptions["spelling"];
  marginMs: number;
  report: Report;
  statuses: {
    overall: StatusCounts;
    songs: ({ slug: string } & StatusCounts)[];
  };
  /** Only with `--perturb`: the same shape as the stage-1 `perturbation`. */
  perturbation?: PerturbationReport;
  /** The adoption criteria for stage 2 against stage 1. */
  verdict: StageTwoVerdict;
};

/** What stage 2 produced for one song. */
type SongRefinement = {
  slug: string;
  result: SongResult;
  lines: RefinedLine[];
};

/**
 * Runs stage 2 on one song: the lines stage 1 anchored are forced inside their
 * windows. The lines stage 2 cannot check go back to stage 1's position.
 */
async function refineSong(
  refiner: Refiner,
  song: Song,
  audioPath: string,
  options: RefineOptions,
  baseline: SongResult,
  anchored: readonly AnchoredLine[],
): Promise<SongRefinement> {
  const lines = await refiner.refine({
    audioPath,
    modelDir: options.modelDir,
    lyrics: song.lyrics,
    windows: windowsFromAnchors(anchored),
    spelling: options.spelling,
    ignored: [],
    margin: options.margin,
  });
  return {
    slug: song.slug,
    result: {
      ...baseline,
      predictions: toRefinedPredictions(anchored, lines),
    },
    lines,
  };
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
      refine: { type: "string" },
      spelling: { type: "string" },
      "margin-ms": { type: "string" },
    },
    strict: true,
  });
  const asr = values.asr;
  if (asr === undefined) {
    throw new Error("--asr <name> is required");
  }
  assertAsrName(asr);
  const refineOptions = parseRefineOptions(values);
  const songsDir = resolve(values["songs-dir"]);
  const slugs = selectSongs(await listSongs(songsDir), values.song);

  // Load everything before starting the worker, so a bad file fails fast.
  const songs: Song[] = [];
  for (const slug of slugs) {
    songs.push(await loadSong(songsDir, slug, asr));
  }

  // Stage 2 needs the model and every song's vocals; check them all now too.
  const vocals = new Map<string, string>();
  if (refineOptions !== null) {
    await assertAlignerModelDir(refineOptions.modelDir);
    for (const song of songs) {
      vocals.set(song.slug, await findVocals(songsDir, song.slug));
    }
  }

  const worker = await startWorker(
    alignWorkerCommand(repoRoot),
    refineOptions === null ? ["anchor"] : ["anchor", "refine"],
  );
  const results: SongResult[] = [];
  const anchoredBySong: AnchoredLine[][] = [];
  const refinements: SongRefinement[] = [];
  let refineFailure: { error: unknown } | undefined;
  let perturbation: PerturbationReports | undefined;
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
      anchoredBySong.push(lines);
    }
    // One memo for the baseline and every perturbation: a line whose text and
    // window did not change is not refined again.
    const refiner = new MemoRefiner(new WorkerRefiner(worker.client));
    if (refineOptions !== null) {
      // As for perturbations: a failure must not cost the stage-1 report.
      try {
        for (const [index, song] of songs.entries()) {
          const baseline = results[index];
          const anchored = anchoredBySong[index];
          const audioPath = vocals.get(song.slug);
          if (
            baseline === undefined ||
            anchored === undefined ||
            audioPath === undefined
          ) {
            throw new Error(`${song.slug}: no stage-1 result to refine`);
          }
          const started = performance.now();
          try {
            refinements.push(
              await refineSong(
                refiner,
                song,
                audioPath,
                refineOptions,
                baseline,
                anchored,
              ),
            );
          } catch (error) {
            const reason =
              error instanceof Error ? error.message : String(error);
            throw new Error(`${song.slug}: ${reason}`);
          }
          const seconds = (performance.now() - started) / 1000;
          process.stderr.write(
            `[${index + 1}/${songs.length}] ${song.slug}: refined in ${seconds.toFixed(1)} s\n`,
          );
        }
      } catch (error) {
        refineFailure = { error };
      }
    }
    if (values.perturb && refineFailure !== undefined) {
      process.stderr.write(
        "note: --perturb is skipped because stage 2 failed\n",
      );
    }
    if (values.perturb && refineFailure === undefined) {
      // A failed perturbation must not cost the baseline report, which is
      // already computed: it is printed first and the failure rethrown below.
      try {
        perturbation = await runPerturbations(
          anchorer,
          refineOptions === null
            ? null
            : { refiner, options: refineOptions, vocals, refinements },
          songs,
          results,
        );
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
  let refineJson: RefineJson | undefined;
  if (refineOptions === null) {
    process.stdout.write(formatReport(report));
  } else {
    process.stdout.write(`Stage 1: anchor\n\n${formatReport(report)}`);
    if (refineFailure === undefined) {
      const refineReport = buildReport(refinements.map(({ result }) => result));
      const songCounts = refinements.map(({ slug, lines }) => ({
        slug,
        counts: countStatuses(lines),
      }));
      process.stdout.write(
        `\nStage 2: refine (spelling ${refineOptions.spelling}, margin ${refineOptions.margin} ms)\n\n${formatReport(refineReport)}`,
      );
      process.stdout.write(`\n${formatStatusCounts(songCounts)}`);
      const verdict = stageTwoVerdict(
        report.overall.errors,
        refineReport.overall.errors,
        perturbation?.refine ?? null,
      );
      refineJson = {
        verdict,
        spelling: refineOptions.spelling,
        marginMs: refineOptions.margin,
        report: refineReport,
        statuses: {
          overall: addStatusCounts(songCounts.map(({ counts }) => counts)),
          songs: songCounts.map(({ slug, counts }) => ({ slug, ...counts })),
        },
        ...(perturbation?.refine == null
          ? {}
          : { perturbation: perturbation.refine }),
      };
    }
  }
  if (perturbation !== undefined) {
    const staged = perturbation.refine !== null;
    process.stdout.write(
      `\n${formatPerturbationReport(perturbation.anchor, staged ? "Stage 1 perturbation" : undefined)}`,
    );
    if (perturbation.refine !== null) {
      process.stdout.write(
        `\n${formatPerturbationReport(perturbation.refine, "Stage 2 perturbation")}`,
      );
    }
  }
  if (refineJson !== undefined) {
    // After the perturbation blocks, which one of its criteria reads.
    process.stdout.write(`\n${formatStageTwoVerdict(refineJson.verdict)}`);
  }
  if (values.out !== undefined) {
    const out = resolve(values.out);
    await mkdir(dirname(out), { recursive: true });
    const json = {
      asr,
      worker: worker.hello.worker,
      report,
      ...(refineJson === undefined ? {} : { refine: refineJson }),
      ...(perturbation === undefined
        ? {}
        : { perturbation: perturbation.anchor }),
    };
    await writeFile(out, `${JSON.stringify(json, null, 2)}\n`);
  }
  if (refineFailure !== undefined) {
    throw refineFailure.error;
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
