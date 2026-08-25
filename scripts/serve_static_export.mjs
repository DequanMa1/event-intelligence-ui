import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("../out", import.meta.url)));
const port = Number(process.env.PORT ?? 3000);
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
};

function findFile(pathname) {
  const relative = normalize(decodeURIComponent(pathname)).replace(/^([/\\])+/, "");
  const candidates = pathname === "/" ? ["index.html"] : [relative, `${relative}.html`, join(relative, "index.html")];
  for (const candidate of candidates) {
    const absolute = resolve(root, candidate);
    if (absolute.startsWith(`${root}\\`) && existsSync(absolute) && statSync(absolute).isFile()) return absolute;
  }
  return null;
}

createServer((request, response) => {
  const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
  const file = findFile(pathname);
  if (!file) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
    return;
  }
  response.writeHead(200, { "content-type": mimeTypes[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Static site available at http://127.0.0.1:${port}`);
});
