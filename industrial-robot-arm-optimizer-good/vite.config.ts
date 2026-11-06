import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Project-site path. CI overrides this with `vite build --base` from
// actions/configure-pages on push, and uses the same path on pull requests.
const PAGES_BASE = '/PerOpt_Good/';

export default defineConfig(({ mode, command }) => {
    const env = loadEnv(mode, '.', '');
    // Never inline a committed key. CI and local builds may set GEMINI_API_KEY;
    // an empty string keeps the public bundle free of secrets.
    const geminiKey = env.GEMINI_API_KEY || '';
    return {
      base: command === 'build' ? PAGES_BASE : '/',
      server: {
        port: 3000,
        host: '0.0.0.0',
      },
      plugins: [react()],
      define: {
        'process.env.API_KEY': JSON.stringify(geminiKey),
        'process.env.GEMINI_API_KEY': JSON.stringify(geminiKey)
      },
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});
