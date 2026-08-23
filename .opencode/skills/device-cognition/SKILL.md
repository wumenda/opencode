---
name: device-cognition
description: 装置认知——从 PFD 图纸提取设备拓扑，再从工艺包文档提取工序说明与反应方程式。当需要建立对某套装置的结构化认知（设备清单 + 连接关系 + 工艺背景）时使用。
---

# 装置认知编排（pfd_topology → process_package）

`device-cognition` 把 pdf2json MCP 服务器的两个业务工具按顺序编排执行，
用于建立对一套化工装置的结构化认知：先用 `pfd_topology` 从 PFD 工艺流程图
提取设备节点与拓扑连接，再用 `process_package` 从工艺包文档提取对应章节的
工序说明与反应方程式，作为装置认知的工艺背景补充。

## 编排顺序

严格按以下顺序调用，不可调换、不可跳过：

1. 调用工具 `pfd_topology`
   - 参数：`pdf_path`（必填）= `/PFD.pdf`。
   - 其余参数（`start_page` / `end_page` / `dpi` / `process_description_path` /
     `equipment_table_path` / `max_workers` / `output_file`）可选，按默认值即可。
2. 等待 `pfd_topology` 返回 `status: "success"` 后，调用工具 `process_package`
   - 参数：`pdf_path`（必填）= `/1万吨异戊烯工艺包文字.pdf`，
     `chapter_index`（必填）= `2`。
   - 其余参数（`chapter_title` / `output_file`）可选，按默认值即可。

## 说明

- 两个工具均来自 **pdf2json**（PFD 工作流）MCP 服务器。
- `pfd_topology` 解析 PFD 图纸，提取设备节点（塔/反应器/换热器/泵等）、
  边界节点与节点间连接关系（拓扑）；提取完成后弹出审核 UI，
  用户审核通过后落盘最终结果。
- `process_package` 从工艺包 PDF 按章节（`chapter_index=2` 表示第 2 章）
  提取结构化工序说明与反应方程式；提取完成后弹出审核 UI，
  用户审核通过后落盘最终结果。
- 两个工具均依赖 VLM 调用，耗时较长；运行期连续推送
  `notifications/progress`，进度 UI 实时渲染当前步骤进度。
- 步骤之间不要并发；串行等待前一步完成即下一步成功执行的前置条件。
- 若某一步返回 `status != "success"`，停止后续步骤并向用户说明失败原因。
