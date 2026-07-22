import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// 개발 서버: 컨테이너에서 5173 노출.
// /api → Django(core) 프록시 → 브라우저는 same-origin으로 호출(CORS 불필요).
export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0',
        port: 5173,
        watch: { usePolling: true }, // Docker 볼륨에서 HMR 안정화
        proxy: {
            '/api': { target: 'http://core:8000', changeOrigin: true },
        },
    },
});
