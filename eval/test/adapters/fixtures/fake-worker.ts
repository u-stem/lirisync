// Test double for the worker process, speaking just enough of the protocol
// for `startWorker`. The first argument picks the misbehaviour:
//   ok                answers everything and exits 0 on shutdown
//   other-protocol    claims protocol version 2
//   exit-after-hello  exits with code 3 right after answering hello
//   deaf              never answers shutdown and never exits on its own
//   lingering         answers shutdown but never exits on its own
const mode = process.argv[2] ?? "ok";
const PREFIX = "@@lirisync ";

function send(message: object): void {
  process.stdout.write(`${PREFIX}${JSON.stringify(message)}\n`);
}

if (mode === "deaf" || mode === "lingering") setInterval(() => {}, 1000);

for await (const line of console) {
  // Bun yields an empty line when the input ends.
  if (line.trim() === "") continue;
  const request: { id: string; method: string } = JSON.parse(line);
  if (request.method === "hello") {
    const protocol = mode === "other-protocol" ? 2 : 1;
    const result = { protocol, worker: "fake", methods: ["hello", "shutdown"] };
    send({ id: request.id, type: "result", result });
    if (mode === "exit-after-hello") process.exit(3);
  } else if (request.method === "shutdown" && mode !== "deaf") {
    send({ id: request.id, type: "result", result: {} });
    if (mode !== "lingering") process.exit(0);
  }
}
