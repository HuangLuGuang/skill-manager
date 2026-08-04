import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

const IGNORED_PARTS = new Set([
  ".git",
  ".venv",
  "node_modules",
  "__pycache__",
  "dist",
  "build",
  ".DS_Store",
]);

// Bytes 0x80-0xff in Python's cp437 codec. This keeps the TypeScript client
// aligned with the server's compatibility normalization for mojibake ZIP names.
const CP437_EXTENDED =
  "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ";
const CP437_CHARS = Array.from(CP437_EXTENDED);

function normalizeZipMojibake(value: string): string {
  const bytes: number[] = [];
  for (const character of Array.from(value)) {
    const codePoint = character.codePointAt(0);
    if (codePoint !== undefined && codePoint <= 0x7f) {
      bytes.push(codePoint);
      continue;
    }
    const index = CP437_CHARS.indexOf(character);
    if (index < 0) return value;
    bytes.push(0x80 + index);
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(bytes),
    );
  } catch {
    return value;
  }
}

type SkillFile = {
  absolutePath: string;
  relativePath: string;
};

async function listFiles(root: string, current = root): Promise<SkillFile[]> {
  const entries = await fs.readdir(current, { withFileTypes: true });
  const files: SkillFile[] = [];
  for (const entry of entries) {
    if (IGNORED_PARTS.has(entry.name)) continue;
    const absolutePath = path.join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(root, absolutePath)));
    } else if (entry.isFile()) {
      const originalParts = path.relative(root, absolutePath).split(path.sep);
      if (originalParts.some((part) => IGNORED_PARTS.has(part))) continue;
      files.push({
        absolutePath,
        relativePath: originalParts.map(normalizeZipMojibake).join("/"),
      });
    }
    // Symbolic links and other special file types are intentionally skipped.
  }
  return files;
}

async function fileSha256(absolutePath: string): Promise<string> {
  const content = await fs.readFile(absolutePath);
  return createHash("sha256").update(content).digest("hex");
}

function compareCanonicalPaths(left: string, right: string): number {
  const leftCodePoints = Array.from(left, (character) => character.codePointAt(0)!);
  const rightCodePoints = Array.from(right, (character) => character.codePointAt(0)!);
  const sharedLength = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < sharedLength; index += 1) {
    const difference = leftCodePoints[index] - rightCodePoints[index];
    if (difference !== 0) return difference;
  }
  return leftCodePoints.length - rightCodePoints.length;
}

export async function computeSkillSignature(root: string): Promise<string> {
  const files = (await listFiles(root)).sort((left, right) =>
    compareCanonicalPaths(left.relativePath, right.relativePath),
  );
  let payload = "";
  for (const file of files) {
    payload += `${file.relativePath}:${await fileSha256(file.absolutePath)}\n`;
  }
  return createHash("sha256").update(payload).digest("hex");
}
