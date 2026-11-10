/**
 * Zod types for the worker's wire messages. `protocol/worker.schema.json` is
 * the source of truth; these are written by hand for their static types and
 * checked against the schema by `test/adapters/worker-protocol.test.ts`.
 */
import { Ms } from "@lirisync/core";
import { z } from "zod";

export const PROTOCOL_PREFIX = "@@lirisync ";
export const PROTOCOL_VERSION = 1;

/** JSON Schema counts string length in code points, not UTF-16 units. */
function codePoints(text: string): number {
  return [...text].length;
}

function isUnique(items: readonly string[]): boolean {
  return new Set(items).size === items.length;
}

const RequestId = z.string().min(1);
const JsonObject = z.record(z.string(), z.unknown());

export const ErrorCode = z.enum([
  "invalid_request",
  "unknown_method",
  "unsupported_version",
  "internal",
  "gpu_unavailable",
  "model_missing",
  "asr_degenerate",
  "cancelled",
  "ffmpeg_missing",
  "audio_unreadable",
]);
export type ErrorCode = z.infer<typeof ErrorCode>;

export const Request = z.strictObject({
  v: z.literal(PROTOCOL_VERSION),
  id: RequestId,
  method: z.string().min(1),
  params: JsonObject,
});

export const Progress = z.strictObject({
  id: RequestId,
  type: z.literal("progress"),
  stage: z.string().min(1),
  ratio: z.number().min(0).max(1),
  etaMs: Ms.nullable(),
});
export type Progress = z.infer<typeof Progress>;

const Result = z.strictObject({
  id: RequestId,
  type: z.literal("result"),
  result: JsonObject,
});

const ErrorMessage = z.strictObject({
  id: z.string().nullable(),
  type: z.literal("error"),
  code: ErrorCode,
  message: z.string(),
});

export const Response = z.discriminatedUnion("type", [
  Progress,
  Result,
  ErrorMessage,
]);
export type Response = z.infer<typeof Response>;

export const HelloResult = z.strictObject({
  protocol: z.literal(PROTOCOL_VERSION),
  worker: z.string().min(1),
  methods: z.array(z.string().min(1)).refine(isUnique, "methods repeat"),
});
export type HelloResult = z.infer<typeof HelloResult>;

const AnchorWord = z.strictObject({
  startMs: Ms,
  endMs: Ms,
  text: z.string(),
});

export const AnchorParams = z.strictObject({
  lyrics: z.array(z.string()),
  words: z.array(AnchorWord),
  ignored: z
    .array(z.string().refine((c) => codePoints(c) === 1, "one character"))
    .refine(isUnique, "ignored characters repeat"),
});
export type AnchorParams = z.infer<typeof AnchorParams>;

const AnchoredLine = z.strictObject({
  status: z.enum(["anchor", "unmatched", "not_sung"]),
  startMs: Ms.nullable(),
  endMs: Ms.nullable(),
  matchRatio: z.number().min(0).max(1),
  ambiguous: z.boolean(),
});

export const AnchorResult = z.strictObject({ lines: z.array(AnchoredLine) });
export type AnchorResult = z.infer<typeof AnchorResult>;

export const SeparateParams = z.strictObject({
  input: z.string().min(1),
  output: z.string().min(1),
  model: z.string().min(1),
});
export type SeparateParams = z.infer<typeof SeparateParams>;

export const SeparateResult = z.strictObject({
  durationMs: Ms,
  sampleRate: z.literal(44100),
  channels: z.literal(2),
});
export type SeparateResult = z.infer<typeof SeparateResult>;
