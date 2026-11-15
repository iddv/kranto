// The cut of the factory, proved in the page (the import test's item 5): no file
// of src/ imports a page that left with builds, projects, repos, the editor and the queue, and
// none names one of the factory's routes. A new file that brings one back fails here. The
// routes are written in pieces so this file does not name them itself.
import { describe, expect, it } from "vitest";

const SOURCES = import.meta.glob(["./**/*.svelte", "./**/*.ts", "./**/*.json", "!./cut.test.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** The page folders and files that left (C3) */
const GONE_FOLDERS = ["pages/builds", "pages/projects", "pages/repos", "pages/today"];
const GONE_FILES = [
  "pages/ideas/IdeaBuild", "pages/ideas/IdeaNew", "pages/ideas/EditorPage", "pages/ideas/ChangesList", "pages/ideas/CapWith", "pages/ideas/scope", "pages/ideas/IdeasLoopList",
  "pages/settings/BuildingList", "pages/settings/BuildingPane", "pages/settings/PublishingList", "pages/settings/PublishingPane", "pages/settings/ExtList", "pages/settings/ExtPane",
  "pages/settings/MaintenanceList", "pages/settings/MaintenancePane", "pages/settings/RulesList", "pages/settings/RulesPane", "pages/settings/GithubList", "pages/settings/GithubPane",
  "pages/settings/EvaluationList", "pages/settings/EvaluationPane", "pages/settings/LearningList", "pages/settings/LearningPane", "pages/settings/ProjectsSetList", "pages/settings/ProjectsSetPane",
  "pages/settings/claudeLogin", "pages/settings/ClaudeLoginRow", "pages/settings/PluginPane", "pages/settings/McpPane", "pages/settings/CapPane", "pages/settings/MergePolicyDialog",
  "pages/settings/MergeSec", "pages/settings/BackfillDialog", "pages/settings/AdoptedPane", "pages/settings/AddPane", "pages/settings/AccountsList",
  "pages/welcome/BuildingStep", "pages/welcome/ReposStep", "pages/welcome/RepoPicker", "pages/welcome/repos", "pages/trace/Compare", "api/actions.gen",
];
/** the factory's routes on the page's own server (CUT/PLAN.md: they answer 404 after C2) */
const GONE_ROUTES = ["loop/", "maintain", "projects", "builds", "act"].map((r) => "api/" + r);

/** a file's imports: static, dynamic and type-only */
const importsOf = (text: string): string[] => [...text.matchAll(/(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']/g)].map((m) => m[1]!);
/** an import's target, from src/, without its extension: "./x/../pages/today/today.ts" → "pages/today/today" */
function target(file: string, spec: string): string {
  const parts = file.replace(/^\.\//, "").split("/").slice(0, -1);
  for (const p of spec.split("/")) {
    if (p === "..") parts.pop();
    else if (p !== ".") parts.push(p);
  }
  return parts.join("/").replace(/\.(svelte\.ts|svelte|ts|js|json)$/, "");
}

describe("the factory left the page (C3)", () => {
  it("has none of the page folders that left", () => {
    const left = Object.keys(SOURCES).filter((f) => GONE_FOLDERS.some((d) => f.startsWith("./" + d + "/")) || GONE_FILES.some((g) => f.replace(/\.(svelte\.ts|svelte|ts)$/, "") === "./" + g));
    expect(left).toEqual([]);
  });

  it("imports no page that left", () => {
    const bad: string[] = [];
    for (const [f, text] of Object.entries(SOURCES)) {
      if (f.endsWith(".json")) continue;
      for (const spec of importsOf(text)) {
        if (!spec.startsWith(".")) continue;
        const t = target(f, spec);
        if (GONE_FOLDERS.some((d) => t === d || t.startsWith(d + "/")) || GONE_FILES.includes(t)) bad.push(`${f}: ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("names none of the factory's routes", () => {
    const bad: string[] = [];
    for (const [f, text] of Object.entries(SOURCES)) {
      for (const r of GONE_ROUTES) {
        // api/act and api/projects as whole names: api/activity and api/actions are other routes
        const re = r.endsWith("/") ? new RegExp(r.replace(/\//g, "\\/")) : new RegExp(r.replace(/\//g, "\\/") + "(?![a-z_])");
        if (re.test(text)) bad.push(`${f}: ${r}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("knows the paths it walks", () => {
    expect(target("./lib/app/data.ts", "../../pages/today/today")).toBe("pages/today/today");
    expect(target("./pages/front/Home.svelte", "./needs")).toBe("pages/front/needs");
    expect(importsOf(`import X from "./a.svelte";\nimport type { Y } from '../b';\nconst Z = () => import("./c.svelte");`)).toEqual(["./a.svelte", "../b", "./c.svelte"]);
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
  });
});
