import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  site: process.env.SITE || 'https://r9700.jjgo.io',
  srcDir: process.env.GITHUB_PAGES === 'true' ? './.local/pages-src' : './src',
  outDir: process.env.GITHUB_PAGES === 'true' ? './dist-pages' : './dist',
  output: process.env.GITHUB_PAGES === 'true' ? 'static' : 'server',
  adapter: process.env.GITHUB_PAGES === 'true' ? undefined : node({ mode: 'standalone', bodySizeLimit: 16*1024 }),
  devToolbar: { enabled: false },
  server: { host: '127.0.0.1', port: 4321 },
});
