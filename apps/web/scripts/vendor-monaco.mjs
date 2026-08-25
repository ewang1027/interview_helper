/**
 * Copy Monaco out of node_modules into `public/monaco/vs`.
 *
 * `@monaco-editor/react` loads the editor at runtime from
 * `https://cdn.jsdelivr.net/npm/monaco-editor@…/min/vs` unless told otherwise — so a
 * self-hosted deployment with no egress has a code workspace that never finishes loading,
 * and every candidate's editor depends on a third party staying up. The version is also
 * whatever the loader package pins, not the one in this lockfile.
 *
 * So the bundle is served from this app. It is ~24MB of hashed files, which is why it is
 * copied at build time and gitignored rather than committed: it is a build artifact of a
 * dependency, and the lockfile already pins which one.
 *
 * Idempotent — a stamp file records the version copied, so `predev` on an unchanged tree
 * costs one `readFile` rather than 24MB of I/O.
 */
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

// The package directory by path, not `require.resolve`: monaco-editor's `exports` map
// does not expose its own package.json, so resolving it throws MODULE_NOT_FOUND.
const pkgDir = join(root, "node_modules", "monaco-editor");
const version = JSON.parse(await readFile(join(pkgDir, "package.json"), "utf8")).version;
const source = join(pkgDir, "min", "vs");
const target = join(root, "public", "monaco", "vs");
const stamp = join(root, "public", "monaco", ".version");

const current = await readFile(stamp, "utf8").catch(() => null);
if (current === version) {
  console.log(`monaco ${version} already vendored`);
  process.exit(0);
}

console.log(`vendoring monaco ${version} -> public/monaco/vs`);
await rm(join(root, "public", "monaco"), { recursive: true, force: true });
await mkdir(dirname(target), { recursive: true });
await cp(source, target, { recursive: true });
await writeFile(stamp, version);
console.log("done");
