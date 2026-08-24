# 服务端示例

最小 MCP Server，演示三种工具模式与 UI 资源注册。

**架构**：每个工具绑定一个独立的 ui 项目（一个工具一个项目），三个 ui 项目各自构建 `dist/index.html`，通过各自的 `ui://` 资源路径对外暴露。

## 前置条件

1. 构建 UI（三个独立 ui 项目，按需构建）：

   ```bash
   cd ../simple-ui/ui   && npm install && npm run build   # 生成 simple-ui/ui/dist/index.html
   cd ../progress-ui/ui && npm install && npm run build   # 生成 progress-ui/ui/dist/index.html
   cd ../review-ui/ui   && npm install && npm run build   # 生成 review-ui/ui/dist/index.html
   ```

2. 安装依赖：`pip install fastmcp>=3.4.4`

## 启动

在 `mcp-apps-ui` 根目录执行：

```bash
cd ..
python -m server_example.server
```

Server 启动在 http://127.0.0.1:8000。

## 工具清单

| 工具 | 模式 | UI 资源 URI | UI 项目 | 说明 |
|------|------|-------------|---------|------|
| `simple_tool` | 快速返回 | `ui://mcp-app-ui/simple/index.html` | `simple-ui/` | 无进度推送，直接返回结果 |
| `progress_tool` | 进度推送 | `ui://mcp-app-ui/progress/index.html` | `progress-ui/` | 逐步推送 progress 通知，返回结果 |
| `review_tool` | 审核阻塞 | `ui://mcp-app-ui/review/index.html` | `review-ui/` | 推送进度 + review_pending 阻塞 + submit_review 唤醒 |
| `submit_review` | 反向调用 | (无独立 UI) | — | UI 点击通过/驳回时反向调用，唤醒阻塞的 review_tool |
| `read_image` | 反向调用 | (无独立 UI) | — | UI 通过此工具读取图片为 base64 data URL |

## 关键模式

### UI 资源注册（一个工具一个独立 ui 项目）

每个工具绑定独立的 `ui://` 资源，资源函数返回对应 ui 项目的构建产物：

```python
@mcp.tool(app=AppConfig(resource_uri="ui://mcp-app-ui/review/index.html"))
async def review_tool(ctx: Context, ...): ...

@mcp.resource("ui://mcp-app-ui/review/index.html")
def get_review_ui_html() -> str:
    with open("../review-ui/ui/dist/index.html") as f:
        return f.read()
```

### 进度推送（携带 uiEvent）

```python
await send_progress_with_data(ctx, progress=1, total=3, message="步骤 1", ui_event={"key": "value"})
```

前端从 `progress.uiEvent.key` 读取数据。

### 审核阻塞

1. `review_tool` 发送 `review_pending=True` + `review_id` + `final_result` 的 progress 通知
2. `review_tool` 在 `asyncio.Event` 上阻塞
3. UI 展示审核界面，用户点击通过/驳回
4. UI 反向调用 `submit_review` 工具
5. `submit_review` 设置 Event，传递审核结果
6. `review_tool` 唤醒，返回最终结果
