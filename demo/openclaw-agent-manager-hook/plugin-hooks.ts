import { getGuardState, resolveSkillNameFromContext } from "./lib/context.ts";
import { checkTool } from "./lib/agent-manager-client.ts";

type PluginHookEvent = {
  sessionKey?: string;
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

const baseUrl = process.env.AGENT_MANAGER_BASE_URL;

if (!baseUrl) {
  throw new Error("AGENT_MANAGER_BASE_URL is required");
}

export async function before_tool_call(event: PluginHookEvent): Promise<unknown> {
  const sessionKey = event.sessionKey ?? "unknown-session";
  const guardState = getGuardState(event);
  const skillName = resolveSkillNameFromContext(event, guardState);
  if (!skillName) {
    return;
  }

  const toolName =
    (event.context?.toolName as string | undefined) ??
    (event.context?.tool_name as string | undefined) ??
    (event.context?.name as string | undefined) ??
    null;

  if (!toolName) {
    return;
  }

  const result = await checkTool(baseUrl, skillName, toolName, sessionKey);
  if (!result.allowed) {
    return {
      block: true,
      blockReason: `Agent Manager blocked tool ${toolName} for skill ${skillName}`,
    };
  }
}
