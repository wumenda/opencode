---
name: step-12
description: 执行两段式演示流程「解析输入 → 特征提取」。当需要按顺序运行 step1 与 step2 两个 MCP 工具（例如验证 skill→tool 两级 Tab 与进度 UI 链路）时使用。
---

# Steps 1 → 2 orchestration

`step-12` 把 pdf2json MCP 服务器的两个确定性演示工具按顺序编排执行，用于验证
后端 MCP 进度通知、前端 timeline 工具卡与 MCP Apps 侧栏两级 Tab（本 skill 为一级
标签，其下聚合 step1、step2 两个二级 tool 标签）的行为。

## 编排顺序

严格按以下顺序调用，不可调换、不可跳过：

1. 调用工具 `step1`
   - 参数：`iterations`（可选，默认 5，1–20），`message`（可选，进度消息前缀）。
2. 等待 `step1` 返回 `status: "success"` 后，调用工具 `step2`
   - 参数同 `step1`。

## 说明

- 两个工具均来自 **pdf2json**（PFD 工作流）MCP 服务器，无需 PDF 或 VLM，确定性执行。
- 每个工具会在运行期连续推送 `notifications/progress`；进度 UI（共享 step-ui，
  由 `ui://step1/progress.html` / `ui://step2/progress.html` 提供）会实时渲染当前步骤进度。
- 步骤之间不要并发；串行等待前一步完成即下一步成功执行的前置条件。
- 若某一步返回 `status != "success"`，停止后续步骤并向用户说明失败原因。