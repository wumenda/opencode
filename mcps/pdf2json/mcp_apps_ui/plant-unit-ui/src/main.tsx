import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';

// MCP Apps 架构：UI 作为 iframe 由 host 加载，无路由。
// 数据通过 postMessage 从 host 获取（见 mcpApp.ts）。
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
