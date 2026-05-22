import { createHash, createHmac } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

async function listFiles(root: string, current = root): Promise<string[]> {
  const entries = await fs.readdir(current, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const abs = path.join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(root, abs)));
    } else if (entry.isFile()) {
      files.push(path.relative(root, abs).split(path.sep).join("/"));
    }
  }
  return files;
}

async function fileSha256(absPath: string): Promise<string> {
  const content = await fs.readFile(absPath);
  return createHash("sha256").update(content).digest("hex");
}

export async function computeSkillSignature(
  root: string,
  signingKey?: string,
): Promise<string> {
  const files = (await listFiles(root)).sort();
  let payload = "";
  for (const rel of files) {
    const abs = path.join(root, rel);
    payload += `${rel}:${await fileSha256(abs)}\n`;
  }
  if (signingKey) {
    return createHmac("sha256", signingKey).update(payload).digest("hex");
  }
  return createHash("sha256").update(payload).digest("hex");
}
