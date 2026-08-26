import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const projectDir = process.cwd();
const exportDir = path.join(projectDir, "out");
const distDir = path.join(projectDir, "dist");
const clientDir = path.join(distDir, "client");
const serverDir = path.join(distDir, "server");

if (path.basename(distDir) !== "dist" || path.dirname(distDir) !== projectDir) {
  throw new Error("Refusing to stage outside the project dist directory.");
}

await rm(distDir, { recursive: true, force: true });
await mkdir(clientDir, { recursive: true });
await mkdir(serverDir, { recursive: true });
await mkdir(path.join(distDir, ".openai"), { recursive: true });

await cp(exportDir, clientDir, { recursive: true });
await cp(
  path.join(projectDir, "worker", "index.js"),
  path.join(serverDir, "index.js"),
);

const hosting = await readFile(
  path.join(projectDir, ".openai", "hosting.json"),
  "utf8",
);
await writeFile(path.join(distDir, ".openai", "hosting.json"), hosting);

console.log("Sites static bundle staged in dist/.");
