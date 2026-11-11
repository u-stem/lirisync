import { type Ms, parseMs } from "@lirisync/core";
import type { TruthLine } from "./labels";
import { parseSecondsText } from "./seconds";

/** One `[n]` object of an ExEdit object file, with its `[n.m]` parts. */
export type ExoObject = {
  /** The section name, `n`, for messages. */
  index: string;
  /** First frame, 1-based as ExEdit counts. */
  start: number;
  /** Whether the object header says `audio=1` (audio files and audio filters). */
  audio: boolean;
  parts: Map<string, string>[];
};

export type ExoProject = {
  /** Frames per second are `rate / scale`. */
  rate: number;
  scale: number;
  objects: ExoObject[];
};

const POSITIVE_INTEGER = /^[1-9]\d*$/;
const LINE_NUMBER = /^[1-9]\d*$/;
const HEX = /^(?:[0-9a-fA-F]{4})*$/;

function positiveInteger(value: string | undefined, what: string): number {
  if (value === undefined || !POSITIVE_INTEGER.test(value)) {
    throw new Error(
      `${what} must be a positive integer, got ${JSON.stringify(value)}`,
    );
  }
  return Number(value);
}

/**
 * Parses the text of an `.exo` file (already decoded from Shift_JIS) into the
 * fields needed for labels. Unknown sections and keys are kept or ignored, as
 * ExEdit writes many that do not matter here.
 */
export function parseExo(text: string): ExoProject {
  const sections = new Map<string, Map<string, string>>();
  const order: string[] = [];
  let current: Map<string, string> | null = null;
  for (const row of text.split(/\r?\n/)) {
    const header = /^\[(.+)\]$/.exec(row);
    if (header?.[1] !== undefined) {
      current = new Map();
      sections.set(header[1], current);
      order.push(header[1]);
      continue;
    }
    const equals = row.indexOf("=");
    if (current === null || equals <= 0) continue;
    current.set(row.slice(0, equals), row.slice(equals + 1));
  }

  const exedit = sections.get("exedit");
  if (exedit === undefined) {
    throw new Error("not an ExEdit object file: no [exedit] section");
  }
  const objects: ExoObject[] = [];
  for (const name of order) {
    if (!/^\d+$/.test(name)) continue;
    const fields = sections.get(name) ?? new Map<string, string>();
    const parts: Map<string, string>[] = [];
    for (let part = 0; sections.has(`${name}.${part}`); part++) {
      parts.push(sections.get(`${name}.${part}`) ?? new Map());
    }
    objects.push({
      index: name,
      start: positiveInteger(fields.get("start"), `object [${name}]: start`),
      audio: fields.get("audio") === "1",
      parts,
    });
  }
  return {
    rate: positiveInteger(exedit.get("rate"), "[exedit] rate"),
    scale: positiveInteger(exedit.get("scale"), "[exedit] scale"),
    objects,
  };
}

/**
 * The string in an ExEdit `text=` value: UTF-16LE code units in hex, ended by
 * the first zero unit (the rest is padding).
 */
export function decodeExoText(hex: string): string {
  if (!HEX.test(hex)) {
    throw new Error("text is not UTF-16LE hex");
  }
  const units: number[] = [];
  for (let i = 0; i < hex.length; i += 4) {
    const unit = Number.parseInt(
      hex.slice(i + 2, i + 4) + hex.slice(i, i + 2),
      16,
    );
    if (unit === 0) break;
    units.push(unit);
  }
  return String.fromCharCode(...units);
}

/** `frames` of `rate / scale` fps in ms, rounded half up, in integers only. */
function framesToMs(frames: number, rate: number, scale: number): Ms {
  return parseMs(Math.floor((2 * frames * scale * 1000 + rate) / (2 * rate)));
}

function partWith(
  object: ExoObject,
  key: string,
): Map<string, string> | undefined {
  return object.parts.find((part) => part.has(key));
}

/** Where the song's 0 ms is on the timeline: the audio object's start, less its play position. */
function audioOrigin(project: ExoProject): { start: number; position: Ms } {
  // Audio filter objects (delay and so on) are `audio=1` too; only an audio
  // file object is the song.
  const audios = project.objects.filter(
    (object) =>
      object.audio &&
      object.parts.some((part) => part.get("_name") === "音声ファイル"),
  );
  const [audio] = audios;
  if (audio === undefined || audios.length !== 1) {
    throw new Error(
      `expected one audio object, found ${audios.length}: put the song's audio on the timeline once`,
    );
  }
  const where = `object [${audio.index}]`;
  const player = partWith(audio, "再生速度");
  const speed = player?.get("再生速度");
  const position = player?.get("再生位置");
  if (speed === undefined || position === undefined) {
    throw new Error(`${where}: audio has no play speed or play position`);
  }
  if (Number(speed) !== 100) {
    throw new Error(`${where}: audio must play at 100% speed, not ${speed}`);
  }
  return { start: audio.start, position: parseSecondsText(position) };
}

/**
 * The labels in an ExEdit project: each text object whose text is a lyric
 * line number, timed from the start of the one audio object (the song). Throws,
 * naming the object, on anything that would make a label wrong.
 */
export function exoLabels(project: ExoProject): TruthLine[] {
  const origin = audioOrigin(project);
  const byLine = new Map<number, TruthLine>();
  for (const object of project.objects) {
    if (object.audio) continue;
    const hex = partWith(object, "text")?.get("text");
    if (hex === undefined) continue;
    const where = `object [${object.index}]`;
    let text: string;
    try {
      text = decodeExoText(hex).trim();
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`${where}: ${reason}`);
    }
    if (!LINE_NUMBER.test(text)) {
      throw new Error(
        `${where}: text must be a line number: ${JSON.stringify(text)}`,
      );
    }
    const line = Number(text);
    if (byLine.has(line)) {
      throw new Error(`${where}: line ${line} is labeled twice`);
    }
    if (object.start < origin.start) {
      throw new Error(`${where}: starts before the audio`);
    }
    const offset = framesToMs(
      object.start - origin.start,
      project.rate,
      project.scale,
    );
    byLine.set(line, { line, start: parseMs(offset + origin.position) });
  }
  if (byLine.size === 0) {
    throw new Error(
      "no text objects: put one text object per sung line, holding its line number",
    );
  }
  return [...byLine.values()].sort((a, b) => a.line - b.line);
}

/** `ms` as Audacity writes seconds: six decimals, from integers. */
function secondsText(ms: Ms): string {
  const whole = Math.floor(ms / 1000);
  const millis = String(ms % 1000).padStart(3, "0");
  return `${whole}.${millis}000`;
}

/** Point labels in Audacity's format, in start order. */
export function formatAudacityLabels(labels: readonly TruthLine[]): string {
  return [...labels]
    .sort((a, b) => a.start - b.start || a.line - b.line)
    .map(
      ({ line, start }) =>
        `${secondsText(start)}\t${secondsText(start)}\t${line}\n`,
    )
    .join("");
}
