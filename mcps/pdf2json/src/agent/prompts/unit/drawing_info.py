from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("drawing_info", "v1")
class DrawingInfoPromptBuilderV1(PromptBuilder):
    expert_type = "drawing_info"
    version = "v1"
    description = "V1 图纸归档信息提取版：从PFD右下角图注区域提取drawing_id/drawing_name/drawing_number/revision/project/unit"

    _ROLE = """
        你是一个专业的化工PFD工程图纸归档信息提取专家。你的任务是从PFD图纸右下角的图注（标题栏）区域中准确提取图纸归档信息。
        """

    _RULES = """
        【总体原则】
        1. 只提取图中图注（标题栏）区域可见的文字信息，不要凭空编造
        2. 图注通常位于图纸右下角，是一个包含多个字段的表格区域
        3. 如果某个字段在图注中找不到，留空字符串即可
        4. 严格按字段含义对应，不要混淆相似字段

        【字段说明】
        1. drawing_id：图纸唯一标识，完整的图纸编号字符串
           - 是图注中最长、最完整的编号，通常包含项目代号+专业代号+图纸类型+序号
           - 如"E23031-6000-DC00-PFD-0001"、"8100-DW-PFD-001"
           - 如果图注中没有明确的图纸标识号，可从图号中推导
           - 如果实在无法确定，设为空字符串
        2. drawing_name：图纸名称/图名，描述该图纸内容的中文标题
           - 如"脱乙烷塔系统工艺管道及仪表流程图"
        3. drawing_number：图纸编号/图号，drawing_id的末尾短编号部分
           - 是drawing_id去掉项目代号前缀后的短编号，通常只包含图纸类型+序号
           - 常见格式如"PFD-0001"、"DW-001"、"PFD-81001"等
           - 例如：drawing_id为"E23031-6000-DC00-PFD-0001"时，drawing_number应为"PFD-0001"
           - 例如：drawing_id为"8100-DW-PFD-001"时，drawing_number应为"PFD-001"
        4. revision：版本号/修订号，图纸的版本标识
           - 常见格式如"0"、"1"、"A"、"B"、"Rev.1"等
           - 如果没有版本信息，设为空字符串
        5. project：项目名称，该图纸所属的工程项目
           - 如"XX炼化公司810万吨/年常减压装置"
        6. unit：单元/装置名称，图纸所属的工艺单元
           - 如"脱乙烷塔单元"、"常压蒸馏单元"

        【常见图注布局】
        - 图注通常为多行多列表格
        - 上方可能为项目名称和单元名称
        - 中间为图纸名称
        - 下方为图号、版本号等
        - 字段标签可能为中文（如"图名"、"图号"、"版本"）或英文（如"DWG NO."、"REV."）

        【常见混淆与纠正】
        1. drawing_id vs drawing_number：drawing_id是完整编号（如"E23031-6000-DC00-PFD-0001"），drawing_number是末尾短编号（如"PFD-0001"）。两者绝不能相同！drawing_number = drawing_id去掉项目代号前缀后的部分
        2. 项目名称 vs 单元名称：project是整个项目，unit是项目下的具体装置/单元
        3. 版本号可能出现在图号末尾，注意区分
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        1. 仅输出JSON，不要输出额外说明
        2. 所有字段必须存在，找不到的设为空字符串
        3. 不要编造任何信息

        {
          "drawing_info": {
            "drawing_id": "",
            "drawing_name": "",
            "drawing_number": "",
            "revision": "",
            "project": "",
            "unit": ""
          }
        }
        """

    _CHECKLIST = """
        【自检清单】
        □ drawing_id 是否为完整图纸标识号（包含项目代号前缀）
        □ drawing_name 是否为图纸中标注的完整图名
        □ drawing_number 是否为drawing_id的末尾短编号（如PFD-0001），且与drawing_id不同
        □ revision 是否为版本号，而非图号的一部分
        □ project 和 unit 是否区分正确（项目 > 单元）
        □ 所有找不到的字段是否已设为空字符串
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "drawing_info": {
                    "type": "object",
                    "properties": {
                        "drawing_id": {"type": "string"},
                        "drawing_name": {"type": "string"},
                        "drawing_number": {"type": "string"},
                        "revision": {"type": "string"},
                        "project": {"type": "string"},
                        "unit": {"type": "string"},
                    },
                },
            },
        }
