type GuardState = {
  verified_skills?: Record<
    string,
    {
      skill_id: string | null;
      skill_path: string;
      signature_verified: boolean;
      status: string | null;
      risk_level: string | null;
    }
  >;
  blocked_skills?: Record<string, { reason: string }>;
};

type HookEvent = {
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

export function setGuardState(event: HookEvent, state: GuardState): void {
  if (!event.context) {
    event.context = {};
  }
  event.context.skill_manager = state;
}

export function getGuardState(event: HookEvent): GuardState {
  return (event.context?.skill_manager as GuardState | undefined) ?? {};
}

export function resolveSkillNameFromContext(event: HookEvent, guardState: GuardState): string | null {
  const context = event.context ?? {};

  const direct =
    (typeof context.skillName === "string" && context.skillName) ||
    (typeof context.skill_name === "string" && context.skill_name) ||
    null;
  if (direct) {
    return direct;
  }

  const skillPath =
    (typeof context.skillPath === "string" && context.skillPath) ||
    (typeof context.skill_path === "string" && context.skill_path) ||
    null;
  if (!skillPath || !guardState.verified_skills) {
    return null;
  }

  for (const [name, value] of Object.entries(guardState.verified_skills)) {
    if (value.skill_path === skillPath || skillPath.startsWith(value.skill_path)) {
      return name;
    }
  }

  return null;
}
