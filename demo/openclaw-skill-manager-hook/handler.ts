import { discoverVisibleSkills, removeSkillFromBootstrap } from "./lib/discovery.ts";
import { getGuardState, resolveSkillNameFromContext, setGuardState } from "./lib/context.ts";
import {
  canLoad,
  verifySkillSignature,
  type RuntimeCheckResponse,
  type VerifySkillSignatureResponse,
} from "./lib/skill-manager-client.ts";
import { computeSkillSignature } from "./lib/signer.ts";

type HookEvent = {
  type: string;
  action: string;
  sessionKey?: string;
  messages?: string[];
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

type VerifiedSkillState = {
  skill_id: string | null;
  skill_path: string;
  signature_verified: boolean;
  status: string | null;
  risk_level: string | null;
};

type BlockedSkillState = {
  reason: string;
};

const baseUrl = process.env.SKILL_MANAGER_BASE_URL;

if (!baseUrl) {
  throw new Error("SKILL_MANAGER_BASE_URL is required");
}

async function handleBootstrap(event: HookEvent): Promise<void> {
  const sessionKey = event.sessionKey ?? "unknown-session";
  const visibleSkills = await discoverVisibleSkills(event);
  const verifiedSkills: Record<string, VerifiedSkillState> = {};
  const blockedSkills: Record<string, BlockedSkillState> = {};

  for (const skill of visibleSkills) {
    try {
      const localSignature = await computeSkillSignature(
        skill.path,
        process.env.SKILL_MANAGER_SIGNING_KEY,
      );

      const verifyResult: VerifySkillSignatureResponse = await verifySkillSignature(baseUrl, {
        skill_name: skill.name,
        local_signature: localSignature,
        agent_id: sessionKey,
      });

      if (!verifyResult.allowed) {
        blockedSkills[skill.name] = { reason: verifyResult.reason };
        removeSkillFromBootstrap(event, skill);
        continue;
      }

      const loadResult: RuntimeCheckResponse = await canLoad(baseUrl, skill.name, sessionKey);
      if (!loadResult.allowed) {
        blockedSkills[skill.name] = { reason: loadResult.reason };
        removeSkillFromBootstrap(event, skill);
        continue;
      }

      verifiedSkills[skill.name] = {
        skill_id: verifyResult.skill_id ?? null,
        skill_path: skill.path,
        signature_verified: true,
        status: verifyResult.status ?? null,
        risk_level: verifyResult.risk_level ?? null,
      };
    } catch (error) {
      blockedSkills[skill.name] = {
        reason: error instanceof Error ? error.message : String(error),
      };
      removeSkillFromBootstrap(event, skill);
    }
  }

  setGuardState(event, {
    verified_skills: verifiedSkills,
    blocked_skills: blockedSkills,
  });

  if (event.messages && Object.keys(blockedSkills).length > 0) {
    event.messages.push(
      `[skill-manager-guard] blocked skills: ${Object.entries(blockedSkills)
        .map(([name, value]) => `${name} (${value.reason})`)
        .join(", ")}`,
    );
  }
}

const handler = async (event: HookEvent): Promise<unknown> => {
  if (event.type === "agent" && event.action === "bootstrap") {
    await handleBootstrap(event);
    return;
  }
};

export default handler;
