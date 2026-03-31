import http from "node:http";
import os from "node:os";
import path from "node:path";
import { promises as fs } from "node:fs";

const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-hook-test-"));
const safeSkillDir = path.join(tempRoot, "safe-skill");
const blockedSkillDir = path.join(tempRoot, "blocked-skill");

await fs.mkdir(safeSkillDir, { recursive: true });
await fs.mkdir(blockedSkillDir, { recursive: true });
await fs.writeFile(path.join(safeSkillDir, "SKILL.md"), "---\nname: safe-skill\ndescription: ok\n---\n");
await fs.writeFile(path.join(blockedSkillDir, "SKILL.md"), "---\nname: blocked-skill\ndescription: bad\n---\n");

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");

  if (req.method === "POST" && url.pathname === "/api/v1/runtime/verify-skill-signature") {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
    const allowed = body.skill_name === "safe-skill";
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      allowed,
      reason: allowed ? "signature verified" : "signature mismatch",
      skill_id: allowed ? "safe-id" : "blocked-id",
      skill_name: body.skill_name,
      status: allowed ? "APPROVED" : "VETTED",
      risk_level: allowed ? "LOW" : "HIGH",
      signature_match: allowed,
    }));
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/v1/runtime/can-load/safe-skill") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      allowed: true,
      reason: "allowed",
      status: "APPROVED",
      risk_level: "LOW",
    }));
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/v1/runtime/can-load/blocked-skill") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      allowed: false,
      reason: "blocked by policy",
      status: "REJECTED",
      risk_level: "HIGH",
    }));
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/v1/runtime/check-tool") {
    const skillName = url.searchParams.get("skill_name");
    const toolName = url.searchParams.get("tool_name");
    const allowed = !(skillName === "safe-skill" && toolName === "Bash");
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      allowed,
      skill_name: skillName,
      tool_name: toolName,
    }));
    return;
  }

  res.writeHead(404, { "content-type": "text/plain" });
  res.end("not found");
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
if (!address || typeof address === "string") {
  throw new Error("Failed to get test server address");
}

process.env.SKILL_MANAGER_BASE_URL = `http://127.0.0.1:${address.port}`;

const { default: handler } = await import("./handler.ts");
const { before_tool_call } = await import("./plugin-hooks.ts");

const bootstrapEvent = {
  type: "agent",
  action: "bootstrap",
  sessionKey: "session-1",
  messages: [],
  context: {
    skillDirs: [safeSkillDir, blockedSkillDir],
    bootstrapFiles: [
      { path: path.join(safeSkillDir, "SKILL.md") },
      { path: path.join(blockedSkillDir, "SKILL.md") },
    ],
  },
};

await handler(bootstrapEvent);

console.log("Bootstrap result:");
console.log(JSON.stringify(bootstrapEvent, null, 2));

const toolEventAllowed = {
  sessionKey: "session-1",
  context: {
    skill_name: "safe-skill",
    tool_name: "Read",
    skill_manager: bootstrapEvent.context.skill_manager,
  },
};

const toolEventBlocked = {
  sessionKey: "session-1",
  context: {
    skill_name: "safe-skill",
    tool_name: "Bash",
    skill_manager: bootstrapEvent.context.skill_manager,
  },
};

const allowedResult = await before_tool_call(toolEventAllowed);
const blockedResult = await before_tool_call(toolEventBlocked);

console.log("before_tool_call allowed result:");
console.log(JSON.stringify(allowedResult ?? null, null, 2));
console.log("before_tool_call blocked result:");
console.log(JSON.stringify(blockedResult ?? null, null, 2));

server.close();
