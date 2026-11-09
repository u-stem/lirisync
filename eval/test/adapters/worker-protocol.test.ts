import { describe, expect, test } from "bun:test";
import { z } from "zod";
import {
  AnchorParams,
  AnchorResult,
  HelloResult,
  Request,
  Response,
  SeparateParams,
  SeparateResult,
} from "../../adapters/worker-protocol";

const SCHEMA_PATH = `${import.meta.dir}/../../../protocol/worker.schema.json`;
const schema = await Bun.file(SCHEMA_PATH).json();

/** The schema's own verdict on a definition, used as the reference. */
function fromSchema(definition: string): z.ZodType {
  return z.fromJSONSchema({
    $schema: schema.$schema,
    $defs: schema.$defs,
    $ref: `#/$defs/${definition}`,
  });
}

const line = {
  status: "anchor",
  startMs: 1000,
  endMs: 2000,
  matchRatio: 0.5,
  ambiguous: false,
};
const word = { startMs: 1000, endMs: 1200, text: "かぜ" };
const anchorParams = { lyrics: ["風"], words: [word], ignored: ["♪"] };
const separateParams = {
  input: "/music/song.mp3",
  output: "/work/vocals.wav",
  model: "/models/sep.onnx",
};
const separateResult = { durationMs: 3000, sampleRate: 44100, channels: 2 };

type Case = [name: string, value: unknown];

const cases: Record<string, { parser: z.ZodType; values: Case[] }> = {
  Request: {
    parser: Request,
    values: [
      ["a request", { v: 1, id: "r1", method: "hello", params: {} }],
      ["another version", { v: 2, id: "r1", method: "hello", params: {} }],
      ["an empty id", { v: 1, id: "", method: "hello", params: {} }],
      ["an empty method", { v: 1, id: "r1", method: "", params: {} }],
      ["array params", { v: 1, id: "r1", method: "hello", params: [] }],
      ["an extra key", { v: 1, id: "r1", method: "x", params: {}, x: 1 }],
    ],
  },
  Response: {
    parser: Response,
    values: [
      ["a result", { id: "r1", type: "result", result: {} }],
      ["a result without id", { id: null, type: "result", result: {} }],
      ["an array result", { id: "r1", type: "result", result: [] }],
      [
        "a progress",
        { id: "r1", type: "progress", stage: "s", ratio: 1, etaMs: 5 },
      ],
      [
        "a progress without eta",
        { id: "r1", type: "progress", stage: "s", ratio: 0, etaMs: null },
      ],
      [
        "a progress past 1",
        { id: "r1", type: "progress", stage: "s", ratio: 1.5, etaMs: null },
      ],
      [
        "a fractional eta",
        { id: "r1", type: "progress", stage: "s", ratio: 0, etaMs: 1.5 },
      ],
      ["an error", { id: "r1", type: "error", code: "internal", message: "m" }],
      [
        "an error without id",
        { id: null, type: "error", code: "invalid_request", message: "m" },
      ],
      [
        "an unknown error code",
        { id: "r1", type: "error", code: "nope", message: "m" },
      ],
      [
        "an ffmpeg_missing error",
        { id: "r1", type: "error", code: "ffmpeg_missing", message: "m" },
      ],
      [
        "an audio_unreadable error",
        { id: "r1", type: "error", code: "audio_unreadable", message: "m" },
      ],
      ["an unknown type", { id: "r1", type: "log", message: "m" }],
      ["an extra key", { id: "r1", type: "result", result: {}, x: 1 }],
    ],
  },
  HelloResult: {
    parser: HelloResult,
    values: [
      ["a hello", { protocol: 1, worker: "0.1.0", methods: ["hello"] }],
      ["another protocol", { protocol: 2, worker: "0.1.0", methods: [] }],
      ["an empty worker", { protocol: 1, worker: "", methods: [] }],
      ["a repeated method", { protocol: 1, worker: "0", methods: ["a", "a"] }],
      ["an empty method", { protocol: 1, worker: "0", methods: [""] }],
    ],
  },
  AnchorParams: {
    parser: AnchorParams,
    values: [
      ["anchor params", anchorParams],
      ["nothing to ignore", { ...anchorParams, ignored: [] }],
      ["an astral ignored character", { ...anchorParams, ignored: ["😀"] }],
      ["two ignored characters in one", { ...anchorParams, ignored: ["ab"] }],
      ["an empty ignored item", { ...anchorParams, ignored: [""] }],
      [
        "a repeated ignored character",
        { ...anchorParams, ignored: ["a", "a"] },
      ],
      [
        "a negative word start",
        { ...anchorParams, words: [{ ...word, startMs: -1 }] },
      ],
      [
        "a fractional word end",
        { ...anchorParams, words: [{ ...word, endMs: 1.5 }] },
      ],
      [
        "a word with an extra key",
        { ...anchorParams, words: [{ ...word, x: 1 }] },
      ],
      ["missing ignored", { lyrics: [], words: [] }],
    ],
  },
  AnchorResult: {
    parser: AnchorResult,
    values: [
      ["an anchored line", { lines: [line] }],
      [
        "an unmatched line",
        {
          lines: [{ ...line, status: "unmatched", startMs: null, endMs: null }],
        },
      ],
      ["no lines", { lines: [] }],
      ["an unknown status", { lines: [{ ...line, status: "x" }] }],
      ["a fractional start", { lines: [{ ...line, startMs: 1.5 }] }],
      ["a negative end", { lines: [{ ...line, endMs: -1 }] }],
      ["a ratio past 1", { lines: [{ ...line, matchRatio: 1.5 }] }],
      ["a missing ambiguous", { lines: [{ ...line, ambiguous: undefined }] }],
      ["an extra key", { lines: [], x: 1 }],
    ],
  },
  SeparateParams: {
    parser: SeparateParams,
    values: [
      ["separate params", separateParams],
      ["an empty input", { ...separateParams, input: "" }],
      ["an empty output", { ...separateParams, output: "" }],
      ["an empty model", { ...separateParams, model: "" }],
      ["a numeric input", { ...separateParams, input: 1 }],
      ["a missing model", { input: "a.mp3", output: "b.wav" }],
      ["an extra key", { ...separateParams, x: 1 }],
    ],
  },
  SeparateResult: {
    parser: SeparateResult,
    values: [
      ["a separate result", separateResult],
      ["no duration", { ...separateResult, durationMs: 0 }],
      ["a negative duration", { ...separateResult, durationMs: -1 }],
      ["a fractional duration", { ...separateResult, durationMs: 1.5 }],
      ["another sample rate", { ...separateResult, sampleRate: 48000 }],
      ["mono", { ...separateResult, channels: 1 }],
      ["a missing channels", { durationMs: 1, sampleRate: 44100 }],
      ["an extra key", { ...separateResult, x: 1 }],
    ],
  },
};

describe.each(Object.entries(cases))(
  "%s agrees with the schema",
  (definition, { parser, values }) => {
    const reference = fromSchema(definition);
    // Guards against a fixture typo that makes every case invalid, in which
    // case a parser rejecting everything would agree with the schema.
    test("the first case is valid", () => {
      const [, first] = values[0] ?? ["", undefined];
      expect(reference.safeParse(first).success).toBe(true);
    });
    test.each(values)("on %s", (_, value) => {
      const expected = reference.safeParse(value).success;
      expect(parser.safeParse(value).success).toBe(expected);
    });
  },
);
