// Start the backend, the dashboard and the agent's service together.
// The backend and the service share AGENT_SERVICE_KEY: the one in .env if it is
// there, or a fresh one for this session.
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import concurrently from "concurrently";

function fromEnvFile(name) {
  if (!existsSync(".env")) return "";
  const line = readFileSync(".env", "utf8")
    .split(/\r?\n/)
    .find((l) => l.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).trim() : "";
}

const key =
  process.env.AGENT_SERVICE_KEY ||
  fromEnvFile("AGENT_SERVICE_KEY") ||
  randomBytes(32).toString("hex");
const env = { AGENT_SERVICE_KEY: key };

const { result } = concurrently(
  [
    { command: "npm run dev:backend", name: "backend", env },
    { command: "npm run dev:dashboard", name: "dashboard" },
    { command: "npm run dev:agent", name: "agent", env },
  ],
  { killOthersOn: ["failure", "success"] },
);
result.catch(() => process.exit(1));
