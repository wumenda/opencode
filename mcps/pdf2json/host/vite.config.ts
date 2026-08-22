import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// host 测试前端：默认端口 5174（避开 ui/ 的 5173）。
// 构建后产物在 host/dist/，仅用于本地测试，无需输出到项目根 static/。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
  },
  build: {
    outDir: 'dist',
  },
});