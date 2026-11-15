// Kranto UI's build. `npm run build` writes ../static/app/: hashed files and
// .vite/manifest.json, which routes/static.py reads to link them from app.html. No CDN, no
// inline script, no polyfill (the CSP is script-src 'self').
//
// `npm run dev` serves on 127.0.0.1:5173 only. Open http://127.0.0.1:5173/brb/: the page is the
// scratch Kranto's own (KRANTO_DEV_TARGET, default http://127.0.0.1:8800) with its built module
// swapped for these sources and hot reload; everything else under /brb/, /api and /auth is
// proxied there with Origin rewritten, so the server's same-origin check passes.
/// <reference types="vitest/config" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig, type Plugin } from "vite";

const target = (process.env.KRANTO_DEV_TARGET || "http://127.0.0.1:8800").replace(/\/$/, "");
const proxied = { target, changeOrigin: true, headers: { origin: target } };

function devPage(): Plugin {
  return {
    name: "kranto-dev-page",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const path = (req.url || "").split("?")[0];
        if (path === "/") {
          res.statusCode = 302;
          res.setHeader("location", "/brb/");
          return res.end();
        }
        if (path !== "/brb/" && path !== "/brb/index.html") return next();
        try {
          const html = await (await fetch(`${target}/brb/`)).text();
          const page = html
            .replace(/<script type="module" src="[^"]*\/app\/[^"]*"><\/script>\n?/, "")
            .replace(/<link rel="stylesheet" href="[^"]*\/app\/[^"]*">\n?/g, "")
            .replace("</body>", '<script type="module" src="/src/main.ts"></script>\n</body>');
          res.setHeader("content-type", "text/html; charset=utf-8");
          res.end(await server.transformIndexHtml(path, page));
        } catch (e) {
          res.statusCode = 502;
          res.end(`no Kranto at ${target} (${e}); start a scratch one: kranto up --port 8800`);
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [svelte(), devPage()],
  // component tests mount in jsdom: Svelte's browser build, not its server one
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  base: "./",
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    assetsDir: "",
    manifest: true,
    modulePreload: { polyfill: false },
    target: "es2022",
    sourcemap: false,
    // scripts/dev/build_ui.py holds the gzipped budget (200 KB); the old page's module is one chunk
    chunkSizeWarningLimit: 1024,
    rollupOptions: {
      input: "src/main.ts",
      output: {
        entryFileNames: "app-[hash].js",
        chunkFileNames: "[name]-[hash].js",
        assetFileNames: "[name]-[hash][extname]",
        // the terminal's library, in a chunk of its own: loaded only when Open in Claude Code
        // first opens (scripts/dev/build_ui.py gives it its own budget)
        manualChunks: (id) => (id.includes("/node_modules/@xterm/") ? "xterm" : undefined),
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "^/brb/.+": proxied,
      "/api": proxied,
      "/auth": proxied,
    },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    // a full parallel run on a busy runner loads a page's module in seconds, not milliseconds:
    // a test waits for what it needs (vi.waitFor, a deadline), and this is the ceiling, not 5 s
    testTimeout: 20_000,
  },
});
