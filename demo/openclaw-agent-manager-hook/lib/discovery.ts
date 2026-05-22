import { existsSync } from "node:fs";
import path from "node:path";

export type DiscoveredSkill = {
  name: string;
  path: string;
};

type HookEvent = {
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

function pushIfSkillDir(results: DiscoveredSkill[], dirPath: string): void {
  const manifestPath = path.join(dirPath, "SKILL.md");
  if (existsSync(manifestPath)) {
    results.push({
      name: path.basename(dirPath),
      path: dirPath,
    });
  }
}

export async function discoverVisibleSkills(event: HookEvent): Promise<DiscoveredSkill[]> {
  const results: DiscoveredSkill[] = [];
  const context = event.context ?? {};

  const candidates = [
    ...(Array.isArray(context.skillDirs) ? (context.skillDirs as string[]) : []),
    ...(Array.isArray(context.skills) ? (context.skills as string[]) : []),
  ];

  for (const candidate of candidates) {
    if (typeof candidate === "string") {
      pushIfSkillDir(results, candidate);
      continue;
    }
  }

  const bootstrapFiles = Array.isArray(context.bootstrapFiles)
    ? (context.bootstrapFiles as Array<Record<string, unknown>>)
    : [];

  for (const file of bootstrapFiles) {
    const filePath = typeof file.path === "string" ? file.path : null;
    if (!filePath) continue;
    if (path.basename(filePath) === "SKILL.md") {
      pushIfSkillDir(results, path.dirname(filePath));
    }
  }

  const deduped = new Map<string, DiscoveredSkill>();
  for (const item of results) {
    deduped.set(item.path, item);
  }
  return [...deduped.values()];
}

export function removeSkillFromBootstrap(event: HookEvent, blockedSkill: DiscoveredSkill): void {
  const context = event.context ?? {};
  if (Array.isArray(context.skillDirs)) {
    context.skillDirs = (context.skillDirs as unknown[]).filter((entry) => {
      return !(typeof entry === "string" && entry === blockedSkill.path);
    });
  }
  if (Array.isArray(context.skills)) {
    context.skills = (context.skills as unknown[]).filter((entry) => {
      return !(typeof entry === "string" && entry === blockedSkill.path);
    });
  }
  if (!Array.isArray(context.bootstrapFiles)) {
    return;
  }
  context.bootstrapFiles = (context.bootstrapFiles as Array<Record<string, unknown>>).filter((entry) => {
    const filePath = typeof entry.path === "string" ? entry.path : "";
    return !filePath.startsWith(blockedSkill.path);
  });
}
