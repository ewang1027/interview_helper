/**
 * Copy Monaco out of node_modules into `public/monaco/vs`.
 *
 * `@monaco-editor/react` loads the editor at runtime from
 * `https://cdn.jsdelivr.net/npm/monaco-editor@…/min/vs` unless told otherwise — so a
 * self-hosted deployment with no egress has a code workspace that never finishes loading,
 * and every candidate's editor depends on a third party staying up. The version is also
 * whatever the loader package pins, not the one in this lockfile.
 *
 * So the bundle is served from this app, gitignored rather than committed: it is a build
 * artifact of a dependency, and the lockfile already pins which one.
 *
 * **Not all of it** — see `SKIP`. `min/vs` is Monaco's everything-build and this editor
 * only ever holds Python and C++.
 *
 * Idempotent — a stamp file records what was copied, so `predev` on an unchanged tree
 * costs one `readFile` rather than the whole tree of I/O. The stamp carries `SKIP` as well
 * as the version, so editing the list below re-vendors rather than silently leaving a
 * tree that no longer matches it.
 */
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Left in `node_modules`, 10.5MB of the 23.3MB `min/vs` weighs.
 *
 * Both entries were checked against the code that would request them, not assumed:
 *
 * - **`nls/lang`** (1.7MB, 12 locales). `nls.messages-loader` reads
 *   `availableLanguages["*"]` and calls back immediately unless it is set to something
 *   other than `"en"`. `coding.tsx` configures `paths` and nothing else, so no locale is
 *   ever requested.
 * - **The TypeScript, CSS, HTML and JSON language workers** (8.8MB, `ts.worker` alone
 *   6.7MB). Each is referenced only by its own small loader shim, and a shim runs only
 *   when a model of that language exists. `coding.tsx` sets `language` to `"cpp"` or
 *   `"python"` and there is no other editor in the app. The shims stay, so if one ever
 *   did run it would 404 on the payload rather than fail obscurely — the loud failure of
 *   the two, and the signal that this list needs revisiting.
 *
 * `assets/editor.worker-*` and `assets/editorWebWorkerMain-*` are **not** here: those are
 * the core editor's own workers and are on the critical path for every language.
 *
 * This costs image size and registry pulls, not page load — nothing below was ever
 * fetched by a browser running this app.
 */
const SKIP = [
  "nls/lang",
  "assets/ts.worker-",
  "assets/css.worker-",
  "assets/html.worker-",
  "assets/json.worker-",
];

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

// The package directory by path, not `require.resolve`: monaco-editor's `exports` map
// does not expose its own package.json, so resolving it throws MODULE_NOT_FOUND.
const pkgDir = join(root, "node_modules", "monaco-editor");
const version = JSON.parse(await readFile(join(pkgDir, "package.json"), "utf8")).version;
const source = join(pkgDir, "min", "vs");
const target = join(root, "public", "monaco", "vs");
const stamp = join(root, "public", "monaco", ".version");

const want = `${version} skip:${SKIP.join(",")}`;
const current = await readFile(stamp, "utf8").catch(() => null);
if (current === want) {
  console.log(`monaco ${version} already vendored`);
  process.exit(0);
}

console.log(`vendoring monaco ${version} -> public/monaco/vs`);
await rm(join(root, "public", "monaco"), { recursive: true, force: true });
await mkdir(dirname(target), { recursive: true });
await cp(source, target, {
  recursive: true,
  filter: (from) => {
    const path = relative(source, from).split(sep).join("/");
    return !SKIP.some((skip) => path === skip || path.startsWith(skip));
  },
});
await writeFile(stamp, want);
console.log("done");
