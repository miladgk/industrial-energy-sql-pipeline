/**
 * The dashboard is a static page. Its data lives in ../docs/data (written by
 * scripts/export_dashboard_data.py and committed by the daily refresh), so it
 * is not copied into this folder: the dev server serves it from there, and the
 * build copies it next to the page. `base: './'` keeps every URL relative, so
 * the same build works at the root of a dev server and under the GitHub Pages
 * project path.
 */
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';
import { defineConfig, type Plugin } from 'vite';

const DOCS = path.resolve(__dirname, '../docs');
const SHARED_DIRS = ['data', 'assets']; // docs/data/*.json, docs/assets/favicon.svg

const TYPES: Record<string, string> = {
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
};

function docsStatic(): Plugin {
  return {
    name: 'docs-static',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url || '').split('?')[0]);
        const rel = url.replace(/^\/+/, '');
        if (!SHARED_DIRS.some((d) => rel.startsWith(`${d}/`))) return next();
        const file = path.resolve(DOCS, rel);
        if (!file.startsWith(DOCS + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return next();
        res.setHeader('Content-Type', TYPES[path.extname(file)] || 'application/octet-stream');
        res.setHeader('Cache-Control', 'no-store');
        fs.createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      const out = path.resolve(__dirname, 'dist');
      for (const dir of SHARED_DIRS) {
        const src = path.join(DOCS, dir);
        if (fs.existsSync(src)) fs.cpSync(src, path.join(out, dir), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  base: './',
  publicDir: false,
  plugins: [react(), tailwindcss(), docsStatic()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'static', // keeps the bundle apart from docs/assets
    chunkSizeWarningLimit: 700, // one page, one bundle (React + motion + charts)
  },
});
