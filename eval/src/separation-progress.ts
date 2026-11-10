import type { Progress } from "../adapters/worker-protocol";

const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;

/** `m:ss`, rounded to the nearest second. Minutes are not wrapped into hours. */
export function formatClock(ms: number): string {
  const total = Math.round(ms / MS_PER_SECOND);
  const minutes = Math.floor(total / SECONDS_PER_MINUTE);
  const seconds = total % SECONDS_PER_MINUTE;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** `[n/N] <slug>: NN% (eta m:ss)`; the eta is left out when it is unknown. */
export function formatProgress(
  slug: string,
  index: number,
  total: number,
  ratio: number,
  etaMs: number | null,
): string {
  const eta = etaMs === null ? "" : ` (eta ${formatClock(etaMs)})`;
  return `[${index}/${total}] ${slug}: ${Math.floor(ratio * 100)}%${eta}`;
}

export type ProgressReporterOptions = {
  slug: string;
  /** 1-based position of the song among the selected ones. */
  index: number;
  total: number;
  /** Whether `write` reaches a terminal, where a line can be overwritten. */
  tty: boolean;
  write: (text: string) => void;
};

export type ProgressReporter = {
  update(progress: Pick<Progress, "ratio" | "etaMs">): void;
  /** Ends the line on a terminal, if one was started. */
  finish(): void;
};

const LOG_STEP_PERCENT = 10;

/**
 * Shows progress on one line. It writes only when the integer percent changes
 * (on a terminal) or when a new 10 % step is entered (otherwise, so that a log
 * stays short).
 */
export function createProgressReporter(
  options: ProgressReporterOptions,
): ProgressReporter {
  const { slug, index, total, tty, write } = options;
  let shown = -1;
  let width = 0;
  return {
    update({ ratio, etaMs }) {
      const percent = Math.floor(ratio * 100);
      const key = tty ? percent : Math.floor(percent / LOG_STEP_PERCENT);
      if (key === shown) return;
      shown = key;
      const line = formatProgress(slug, index, total, ratio, etaMs);
      if (tty) {
        write(`\r${line.padEnd(width)}`);
        width = Math.max(width, line.length);
      } else {
        write(`${line}\n`);
      }
    },
    finish() {
      if (tty && shown !== -1) write("\n");
    },
  };
}
