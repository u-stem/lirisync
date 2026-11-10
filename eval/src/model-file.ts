import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";

/** Throws unless `path` is a regular file (a link to one is fine). */
export async function assertModelFile(path: string): Promise<void> {
  const info = await stat(path).catch(() => null);
  if (info === null) {
    throw new Error(`Model file ${path} does not exist`);
  }
  if (!info.isFile()) {
    throw new Error(`Model ${path} is not a file`);
  }
}

/** SHA-256 of a file as lowercase hex, read as a stream: models are large. */
export async function sha256File(path: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}
