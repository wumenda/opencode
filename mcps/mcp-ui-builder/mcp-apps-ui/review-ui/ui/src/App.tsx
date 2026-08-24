/**
 * 应用根组件 -- MCP Apps 架构。
 *
 * 单工具单项目:本 UI 只服务 review_tool 一个工具,直接渲染 ReviewPage。
 * 启动时通过 useMcpInitialize 发起 ui/initialize 握手。
 */

import { useMcpApp, useMcpInitialize } from '@/core/mcpApp';
import { Layout } from '@/components/Layout';
import { LoadingScreen } from '@/components/LoadingScreen';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { useTheme } from '@/hooks/useTheme';
import { ReviewPage } from '@/pages/ReviewPage';

// 副作用 import:注册 review 事件名解析器(progress.uiEvent -> 事件名)
import '@/patterns/review';

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

  if (!app.toolInput) {
    return (
      <Layout>
        <LoadingScreen message="等待任务" />
      </Layout>
    );
  }

  return (
    <ErrorBoundary>
      <div className="h-full animate-fade-in">
        <ReviewPage />
      </div>
    </ErrorBoundary>
  );
}
