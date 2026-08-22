import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import pfdTopologyUi from '../../mcp_apps_ui/pfd-topology-ui/dist/index.html?raw';
import plantUnitUi from '../../mcp_apps_ui/plant-unit-ui/dist/index.html?raw';
import equipmentAssemblyUi from '../../mcp_apps_ui/equipment-assembly-ui/dist/index.html?raw';
import processPackageUi from '../../mcp_apps_ui/process-package-ui/dist/index.html?raw';
import pfdRefluxUi from '../../mcp_apps_ui/pfd-reflux-ui/dist/index.html?raw';
import compositionTableUi from '../../mcp_apps_ui/composition-table-ui/dist/index.html?raw';
import { MOCK_TOOLS, findToolGroup, type MockScenario } from './mockData';
import { HostConnector, type LogEntry } from './hostProtocol';

/** 工具名 → 对应 UI 项目构建产物（注入 toolName 后由 UI 自路由）。 */
const TOOL_TO_UI: Record<string, string> = {
  pfd_topology: pfdTopologyUi,
  plant_unit_topology: plantUnitUi,
  equipment_assembly: equipmentAssemblyUi,
  process_package: processPackageUi,
  pfd_reflux: pfdRefluxUi,
  composition_table: compositionTableUi,
};

/** 注入 window.__MCP_TOOL_NAME__（与后端 _get_ui_html 一致），保证 UI 正确路由。 */
function buildSrcdoc(toolName: string): string {
  const html = TOOL_TO_UI[toolName] ?? pfdTopologyUi;
  const injection = `<script>window.__MCP_TOOL_NAME__=${JSON.stringify(toolName)};</script>`;
  return html.replace('<head>', '<head>' + injection);
}

const PLAY_DELAY_MS = 1200;

export default function App() {
  const [uiReady, setUiReady] = useState<boolean>(false);
  const [toolName, setToolName] = useState<string>(MOCK_TOOLS[0].name);
  const [scenarioId, setScenarioId] = useState<string>(MOCK_TOOLS[0].scenarios[0].id);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [playing, setPlaying] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [stepIndex, setStepIndex] = useState(-1); // 已发送的 progress 步数
  const [phase, setPhase] = useState<'idle' | 'extracting' | 'review'>('idle');

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const connectorRef = useRef<HostConnector | null>(null);
  const stopRef = useRef(false);

  const currentTool = useMemo(() => findToolGroup(toolName), [toolName]);
  const currentScenario: MockScenario | undefined = useMemo(
    () => currentTool?.scenarios.find((s) => s.id === scenarioId),
    [currentTool, scenarioId],
  );

  // 创建 HostConnector（仅一次）
  useEffect(() => {
    const connector = new HostConnector({
      onLog: (entry) => setLogs((prev) => [...prev.slice(-199), entry]),
      onReviewSubmitted: ({ approved, reason }) => {
        setLogs((prev) => [
          ...prev.slice(-199),
          {
            dir: 'host→ui',
            method: 'ui/notifications/tool-result',
            detail: `审核提交后回发最终结果（approved=${approved}${reason ? `, reason=${reason}` : ''}）`,
            ts: Date.now(),
          },
        ]);
        // 用户提交审核后回发最终结果（模拟 server 的响应）
        if (currentScenarioRef.current?.review) {
          const r = currentScenarioRef.current.review;
          connector.sendToolResult(
            r.resultIsError ? undefined : r.result,
            r.resultIsError,
            r.resultErrorText,
          );
        }
      },
    });
    connectorRef.current = connector;
    // ref callback 在 useEffect 之前执行，此时 connectorRef 还为 null，
    // 需要在此补设 iframe 引用，否则 post() 无法发送消息
    if (iframeRef.current) {
      connector.setIframe(iframeRef.current);
    }
    return () => connector.destroy();
  }, []);

  // 跟踪当前场景（供回调使用，避免闭包过期）
  const currentScenarioRef = useRef(currentScenario);
  currentScenarioRef.current = currentScenario;

  // 绑定 iframe（每次 reload 后重新绑定）
  const setIframeRef = useCallback((node: HTMLIFrameElement | null) => {
    iframeRef.current = node;
    connectorRef.current?.setIframe(node);
  }, []);

  // srcdoc：注入 toolName，加载构建好的 UI
  const srcdoc = useMemo(() => buildSrcdoc(toolName), [toolName, reloadKey]);

  // iframe 加载完成 → 允许驱动
  const handleIframeLoad = useCallback(() => setUiReady(true), []);

  // 切换工具/场景时重置播放状态
  const selectTool = useCallback((name: string) => {
    const group = findToolGroup(name);
    setToolName(name);
    setScenarioId(group?.scenarios[0].id ?? '');
    resetPlay();
    setReloadKey((k) => k + 1);
  }, []);

  const selectScenario = useCallback((id: string) => {
    setScenarioId(id);
    resetPlay();
  }, []);

  function resetPlay() {
    stopRef.current = true;
    setPlaying(false);
    setStepIndex(-1);
    setPhase('idle');
  }

  // ---- 手动驱动 ----

  const handleSendInput = useCallback(() => {
    if (!currentScenario) return;
    stopRef.current = true;
    setPlaying(false);
    connectorRef.current?.sendToolInput(currentScenario.toolName, currentScenario.args);
    setPhase('extracting');
    setStepIndex(-1);
  }, [currentScenario]);

  // 无审核场景（失败/异常）：步骤结束后直接回发最终结果
  const sendDirectResult = useCallback((scenario: MockScenario) => {
    const d = scenario.direct;
    if (!d) return;
    connectorRef.current?.sendToolResult(
      d.isError ? undefined : d.result,
      !!d.isError,
      d.errorText,
    );
  }, []);

  const handleNextStep = useCallback(() => {
    if (!currentScenario) return;
    const next = stepIndex + 1;
    if (next < currentScenario.steps.length) {
      connectorRef.current?.sendProgress(currentScenario.steps[next]);
      setStepIndex(next);
    } else if (currentScenario.review) {
      connectorRef.current?.sendReviewPending(
        currentScenario.review.reviewId,
        currentScenario.toolName,
        currentScenario.review.finalResult,
      );
      setPhase('review');
      setStepIndex(currentScenario.steps.length);
    } else if (currentScenario.direct) {
      sendDirectResult(currentScenario);
      setStepIndex(currentScenario.steps.length);
    }
  }, [currentScenario, stepIndex, sendDirectResult]);

  const handleEnterReview = useCallback(() => {
    if (!currentScenario?.review) return;
    connectorRef.current?.sendReviewPending(
      currentScenario.review.reviewId,
      currentScenario.toolName,
      currentScenario.review.finalResult,
    );
    setPhase('review');
    setStepIndex(currentScenario.steps.length);
  }, [currentScenario]);

  const handleSendResult = useCallback(() => {
    if (!currentScenario?.review) return;
    connectorRef.current?.sendToolResult(
      currentScenario.review.resultIsError ? undefined : currentScenario.review.result,
      currentScenario.review.resultIsError,
      currentScenario.review.resultErrorText,
    );
  }, [currentScenario]);

  // ---- 自动播放 ----

  const handleAutoPlay = useCallback(async () => {
    if (!currentScenario) return;
    stopRef.current = false;
    setPlaying(true);
    const connector = connectorRef.current;
    if (!connector) return;

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    // 1. 工具入参
    connector.sendToolInput(currentScenario.toolName, currentScenario.args);
    setPhase('extracting');
    await sleep(600);

    // 2. 逐条 progress
    for (let i = 0; i < currentScenario.steps.length; i++) {
      if (stopRef.current) return;
      connector.sendProgress(currentScenario.steps[i]);
      setStepIndex(i);
      await sleep(PLAY_DELAY_MS);
    }

    // 3. 终态：有审核 → review_pending 等待 UI 提交；否则直接回发结果（失败/异常场景）
    if (currentScenario.review) {
      if (stopRef.current) return;
      connector.sendReviewPending(
        currentScenario.review.reviewId,
        currentScenario.toolName,
        currentScenario.review.finalResult,
      );
      setPhase('review');
      setStepIndex(currentScenario.steps.length);
      // 剩余等待 UI 交互；onReviewSubmitted 会回发 tool-result
    } else if (currentScenario.direct) {
      if (stopRef.current) return;
      sendDirectResult(currentScenario);
      setStepIndex(currentScenario.steps.length);
    } else {
      // 无审核、无 direct 的工具：直接回发结果
      connector.sendToolResult({});
    }
    setPlaying(false);
  }, [currentScenario, sendDirectResult]);

  const handleReload = useCallback(() => {
    resetPlay();
    setUiReady(false);
    setReloadKey((k) => k + 1);
  }, []);

  const handleClearLog = useCallback(() => setLogs([]), []);

  const atEnd = currentScenario
    ? stepIndex >= currentScenario.steps.length
    : false;

  return (
    <div className="host-shell">
      <header className="host-header">
        <h1>PFD 审核 UI · Host 测试控制台</h1>
        <span className="host-version">加载构建产物 <code>static/index.html</code></span>
      </header>

      <div className="host-body">
        {/* 左侧控制面板 */}
        <aside className="host-panel">
          <section className="panel-section">
            <h2>工具</h2>
            <div className="tool-list">
              {MOCK_TOOLS.map((t) => (
                <button
                  key={t.name}
                  className={t.name === toolName ? 'tool-btn active' : 'tool-btn'}
                  onClick={() => selectTool(t.name)}
                  title={t.page}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </section>

          <section className="panel-section">
            <h2>场景</h2>
            <div className="scenario-list">
              {currentTool?.scenarios.map((s) => (
                <button
                  key={s.id}
                  className={s.id === scenarioId ? 'scenario-btn active' : 'scenario-btn'}
                  onClick={() => selectScenario(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </section>

          <section className="panel-section">
            <h2>驱动</h2>
            <div className="btn-grid">
              <button className="btn primary" disabled={playing} onClick={handleAutoPlay}>
                自动播放
              </button>
              <button className="btn" disabled={playing} onClick={handleSendInput}>
                发送入参
              </button>
              <button
                className="btn"
                disabled={playing || phase !== 'extracting' || atEnd}
                onClick={handleNextStep}
              >
                下一步进度
              </button>
              <button
                className="btn"
                disabled={playing || phase !== 'extracting' || !currentScenario?.review}
                onClick={handleEnterReview}
              >
                进入审核态
              </button>
              <button
                className="btn"
                disabled={playing || phase !== 'review' || !currentScenario?.review}
                onClick={handleSendResult}
              >
                发送结果
              </button>
              <button className="btn" onClick={handleReload}>
                重载 iframe
              </button>
            </div>
            <p className="hint">
              进度 {stepIndex < 0 ? '-' : Math.min(stepIndex + 1, currentScenario?.steps.length ?? 0)}/{currentScenario?.steps.length ?? '-'} · 阶段{' '}
              {phase === 'idle' ? '待命' : phase === 'extracting' ? '提取中' : '审核'}
            </p>
          </section>

          <section className="panel-section log-section">
            <div className="log-head">
              <h2>消息日志</h2>
              <button className="btn small" onClick={handleClearLog}>
                清空
              </button>
            </div>
            <div className="log-body">
              {logs.length === 0 && <div className="log-empty">暂无消息（载入 iframe 后自动握手）</div>}
              {logs.map((l, i) => (
                <div key={i} className={l.dir === 'host→ui' ? 'log-line out' : 'log-line in'}>
                  <span className="log-dir">{l.dir}</span>
                  <span className="log-method">{l.method}</span>
                  <span className="log-detail">{l.detail}</span>
                </div>
              ))}
            </div>
          </section>
        </aside>

        {/* 右侧 iframe */}
        <main className="host-stage">
          <div className="stage-toolbar">
            <span className={`status-dot ${uiReady ? 'ready' : ''}`} />
            <span className="stage-title">
              {currentTool?.label}
              <span className="stage-page"> · {currentTool?.page}</span>
            </span>
          </div>
          <iframe
            key={reloadKey}
            ref={setIframeRef}
            title="pfd-review-ui"
            className="stage-iframe"
            srcDoc={srcdoc}
            onLoad={handleIframeLoad}
            sandbox="allow-scripts allow-same-origin allow-modals allow-forms allow-popups"
          />
        </main>
      </div>
    </div>
  );
}