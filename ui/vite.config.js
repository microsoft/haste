// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import envCompatible from 'vite-plugin-env-compatible';

export default defineConfig({
  plugins: [
    react(),
    envCompatible()
  ],
  base: '/',
  build: {
    target: 'es2020',
  },
});