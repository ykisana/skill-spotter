// Extract the parts of Fig autocomplete specs that command templating needs:
// the subcommand tree and which options take an argument. Run with node from the repo root:
//   node bench/methods/fig/extract.mjs bench/.cache/fig/package/build > bench/methods/fig/specs.json
// Fig specs (github.com/withfig/autocomplete) are ISC licensed; see bench/methods/fig/LICENSE.
import { pathToFileURL } from "node:url";
import { existsSync } from "node:fs";
import path from "node:path";

const COMMANDS = `git gh npm pnpm yarn bun npx docker kubectl helm terraform make cargo go pip pip3 uv
poetry python python3 node deno pytest jest vitest ruff mypy tsc eslint prettier brew apt systemctl
aws gcloud az heroku fly flyctl vercel netlify wrangler rails bundle dotnet mvn gradle xcodebuild
fastlane psql mysql curl wget ssh scp rsync tar find rm cp mv ls grep rg sed awk jq kill ps
docker-compose alembic pod swift xcrun adb gradlew sentry-cli stripe supabase firebase openssl
redis-cli mongosh sqlite3 tmux git-lfs pre-commit black isort flake8 pylint tox nox pdm hatch
cypress playwright turbo nx lerna webpack vite next nuxt expo eas`.split(/\s+/).filter(Boolean);

const dir = process.argv[2];
const simplify = (spec, depth = 0) => {
  if (!spec || typeof spec !== "object" || depth > 6) return null;
  const names = (n) => (Array.isArray(n) ? n : [n]).filter((x) => typeof x === "string");
  const out = { names: names(spec.name), subcommands: [], options: [] };
  for (const sub of spec.subcommands || []) {
    const s = simplify(sub, depth + 1);
    if (s && s.names.length) out.subcommands.push(s);
  }
  for (const opt of spec.options || []) {
    const n = names(opt.name);
    if (!n.length) continue;
    const args = opt.args;
    const takesArg = !!args && !(Array.isArray(args) && args.length === 0);
    out.options.push({ names: n, takesArg });
  }
  out.hasArgs = !!spec.args;
  return out;
};

const result = {};
for (const cmd of COMMANDS) {
  const file = path.join(dir, `${cmd}.js`);
  if (!existsSync(file)) continue;
  try {
    const mod = await import(pathToFileURL(path.resolve(file)).href);
    const spec = mod.default ?? mod;
    const simple = simplify(typeof spec === "function" ? spec() : spec);
    if (simple) result[cmd] = simple;
  } catch (e) {
    process.stderr.write(`skip ${cmd}: ${e.message}\n`);
  }
}
process.stdout.write(JSON.stringify(result));
process.stderr.write(`extracted ${Object.keys(result).length} specs\n`);
