/**
 * 应用根组件 -- MCP Apps 架构（PFD 拓扑提取工具独立项目）。
 * 单工具 SPA，直接渲染 MultiPageTopologyPage，无路由。
 * 启动时通过 useMcpInitialize 发起 ui/initialize 握手。
 */
import { useMcpApp, useMcpInitialize } from '@/core/mcpApp';
import { Layout } from '@/components/Layout';
import { LoadingScreen } from '@/components/LoadingScreen';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { useTheme } from '@/hooks/useTheme';
import { MultiPageTopologyPage } from '@/pages/MultiPageTopologyPage';

export default function App() {
  useMcpInitialize();
  useTheme();
  const app = useMcpApp();

  if (app.status === 'initializing') {
    return (
      <Layout>
        <ErrorBoundary>
          <LoadingScreen message="正在连接 host" />
        </ErrorBoundary>
      </Layout>
    );
  }

  if (app.status === 'error' && !app.toolResult) {
    return (
      <Layout>
        <div className="flex h-full items-center justify-center">
          <div className="text-sm text-red">连接失败:{app.error}</div>
        </div>
      </Layout>
    );
  }

  return (
    <ErrorBoundary>
      <div className="h-full animate-fade-in">
        <MultiPageTopologyPage />
      </div>
    </ErrorBoundary>
  );
}
