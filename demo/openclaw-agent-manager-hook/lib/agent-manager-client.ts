export type VerifySkillSignatureRequest = {
  skill_name: string;
  local_signature: string;
  skill_id?: string;
  agent_id?: string;
};

export type VerifySkillSignatureResponse = {
  allowed: boolean;
  reason: string;
  skill_id?: string | null;
  skill_name: string;
  status?: string | null;
  risk_level?: string | null;
  signature_match: boolean;
};

export type RuntimeCheckResponse = {
  allowed: boolean;
  reason: string;
  status?: string | null;
  risk_level?: string | null;
};

export type ToolCheckResponse = {
  allowed: boolean;
  skill_name: string;
  tool_name: string;
};

export async function verifySkillSignature(
  baseUrl: string,
  body: VerifySkillSignatureRequest,
): Promise<VerifySkillSignatureResponse> {
  const response = await fetch(`${baseUrl}/api/v1/runtime/verify-skill-signature`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as VerifySkillSignatureResponse;
}

export async function canLoad(
  baseUrl: string,
  skillName: string,
  agentId?: string,
): Promise<RuntimeCheckResponse> {
  const url = new URL(`${baseUrl}/api/v1/runtime/can-load/${skillName}`);
  if (agentId) {
    url.searchParams.set("agent_id", agentId);
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as RuntimeCheckResponse;
}

export async function checkTool(
  baseUrl: string,
  skillName: string,
  toolName: string,
  agentId?: string,
): Promise<ToolCheckResponse> {
  const url = new URL(`${baseUrl}/api/v1/runtime/check-tool`);
  url.searchParams.set("skill_name", skillName);
  url.searchParams.set("tool_name", toolName);
  if (agentId) {
    url.searchParams.set("agent_id", agentId);
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ToolCheckResponse;
}
