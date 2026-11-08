import { z } from "zod";

/** Integer milliseconds. The only time unit stored in the domain model. */
export const Ms = z.number().int().nonnegative().brand<"Ms">();
export type Ms = z.infer<typeof Ms>;

/** Parses an unknown value into `Ms`. Throws `ZodError` on invalid input. */
export function parseMs(input: unknown): Ms {
  return Ms.parse(input);
}

/** Frame rate as the rational `rate / scale` (e.g. 30000/1001 for 29.97 fps). */
export const FrameRate = z.object({
  rate: z.number().int().positive(),
  scale: z.number().int().positive(),
});
export type FrameRate = z.infer<typeof FrameRate>;

/** Parses an unknown value into `FrameRate`. Throws `ZodError` on invalid input. */
export function parseFrameRate(input: unknown): FrameRate {
  return FrameRate.parse(input);
}

const MS_PER_SECOND = 1000n;
const MAX_SAFE_FRAME = BigInt(Number.MAX_SAFE_INTEGER);

/**
 * Converts milliseconds to a frame index:
 * `floor(ms * rate / (scale * 1000)) + origin`.
 *
 * Integer arithmetic only. Float seconds are unsafe here: 4.1 s * 30 fps is
 * 122.999... and lands one frame early.
 *
 * The product `ms * rate` is computed with BigInt. For 24 h at 60000/1001 it is
 * about 5e12 and would still fit in a Number, but `Ms` allows any safe integer
 * and `rate` is unbounded, so a Number product can pass 2^53 and silently lose
 * precision. BigInt keeps the result exact for every valid input; the cost is
 * negligible at export time.
 *
 * @param origin First frame index of the target format (0 or 1).
 * @throws RangeError if the result is not a safe integer.
 */
export function msToFrame(ms: Ms, frameRate: FrameRate, origin: 0 | 1): number {
  const numerator = BigInt(ms) * BigInt(frameRate.rate);
  const denominator = BigInt(frameRate.scale) * MS_PER_SECOND;
  // Both operands are non-negative, so BigInt truncation equals floor.
  const frame = numerator / denominator + BigInt(origin);
  // Check in BigInt: Number(frame) would round before a safe-integer test.
  if (frame > MAX_SAFE_FRAME) {
    throw new RangeError(
      `Frame index exceeds the safe integer range: ${frame}`,
    );
  }
  return Number(frame);
}
