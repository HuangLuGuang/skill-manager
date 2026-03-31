import { appendFile, mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const stateDir =
  process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), ".openclaw");
const logDir = path.join(stateDir, "logs");
const logFile = path.join(logDir, "hook-payloads.jsonl");

const handler = async (event: Record<string, unknown>) => {
  await mkdir(logDir, { recursive: true });
  const line = JSON.stringify({
    capturedAt: new Date().toISOString(),
    event,
  });
  await appendFile(logFile, line + "\n", "utf-8");
};

export default handler;
