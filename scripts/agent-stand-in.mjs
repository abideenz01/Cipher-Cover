// A stand-in for the agent's service on port 8003, for the end-to-end tests.
// It records each call to /resume and lists them at /calls; it carries nothing on.
import { createServer } from "node:http";

const calls = [];

createServer((request, response) => {
  if (request.method === "POST" && request.url === "/resume") {
    calls.push({ authorization: request.headers.authorization ?? "" });
    response.writeHead(202, { "content-type": "application/json" });
    response.end('{"status":"accepted"}');
    return;
  }
  const body = request.url === "/calls" ? calls : { status: "ok" };
  response.writeHead(200, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}).listen(8003, "127.0.0.1");
