"""[Deprecated] 标注可视化工具模块。

本模块（``load_image`` / ``draw_annotations_from_result``）无任何生产调用方，
标注为已废弃。请勿在生产代码中调用；图片读写应经由 HostClient 协议。
"""

import math
import os

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

PORT_DIRECTION_COLORS = {
    "input": "#0000FF",
    "output": "#00CC00",
    "unknown": "#CCCC00",
}

PORT_CATEGORY_COLORS = {
    "utility": "#9900CC",
}

EQUIPMENT_CENTER_COLOR = "#FF8800"
VIRTUAL_NODE_CENTER_COLOR = "#00CCCC"


def denormalize_coordinates(coords, image_width, image_height):
    if isinstance(coords, (list, tuple)):
        if len(coords) == 2:
            return [int(coords[0] * image_width), int(coords[1] * image_height)]
        elif len(coords) == 4:
            return [
                int(coords[0] * image_width),
                int(coords[1] * image_height),
                int(coords[2] * image_width),
                int(coords[3] * image_height),
            ]
    return coords


def get_chinese_font(size=20):
    chinese_fonts = [
        "msyh.ttc",
        "simhei.ttf",
        "simsun.ttc",
        "fangsong.ttf",
        "kaiti.ttf",
    ]
    for font_name in chinese_fonts:
        try:
            font_path = f"C:/Windows/Fonts/{font_name}"
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def load_image(image_path, long_edge=2048):
    image = Image.open(image_path)
    if image.mode != "RGB":
        image = image.convert("RGB")
    w, h = image.size
    max_dim = max(w, h)
    if max_dim > long_edge:
        scale = long_edge / max_dim
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)
    return image


def draw_bbox_with_label(draw, bbox, color, label="", font=None, line_width=3):
    x1, y1, x2, y2 = bbox
    draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)
    if label:
        if font is None:
            font = get_chinese_font(12)
        draw.text((x1, y1 - 14), label, fill=color, font=font)


def draw_position_marker(draw, position, color="#FF8800", radius=3, outline=None):
    x, y = position
    r = radius
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=outline if outline else color)


def draw_ports_on_image(
    draw, ports, image_width, image_height, color=None, show_classification=False
):
    font = get_chinese_font(max(12, min(image_width, image_height) // 600))
    for port in ports:
        pos = port.get("position", [])
        if pos and len(pos) == 2:
            direction = port.get("direction", "unknown")
            category = port.get("category", "")
            if category and category.lower() == "utility":
                port_color = PORT_CATEGORY_COLORS["utility"]
            elif color:
                port_color = color
            else:
                port_color = PORT_DIRECTION_COLORS.get(direction, PORT_DIRECTION_COLORS["unknown"])
            pixel_pos = denormalize_coordinates(pos, image_width, image_height)
            r = 3
            draw.ellipse(
                [pixel_pos[0] - r, pixel_pos[1] - r, pixel_pos[0] + r, pixel_pos[1] + r],
                fill=port_color,
                outline="white",
            )
            port_label = port.get("label", "")
            if port_label or direction:
                if show_classification:
                    category = port.get("category", "process")
                    vpos = port.get("orientation", "")
                    parts = [direction]
                    if category and category.lower() == "utility":
                        parts.append("util")
                    if vpos and vpos.lower() not in ("unknown", ""):
                        parts.append(vpos)
                    if port_label:
                        parts.append(port_label)
                    text = ":".join(parts)
                else:
                    text = f"{direction}:{port_label}" if port_label else direction
                draw.text((pixel_pos[0] + 14, pixel_pos[1] - 14), text, fill=port_color, font=font)


def draw_arrow(draw, start, end, color="#FF0000", line_width=3, arrow_size=15):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1:
        return
    ux = dx / length
    uy = dy / length
    draw.line([sx, sy, ex, ey], fill=color, width=line_width)
    arrow_angle = math.pi / 6
    cos_a = math.cos(arrow_angle)
    sin_a = math.sin(arrow_angle)
    left_x = ex - arrow_size * (ux * cos_a + uy * sin_a)
    left_y = ey - arrow_size * (uy * cos_a - ux * sin_a)
    right_x = ex - arrow_size * (ux * cos_a - uy * sin_a)
    right_y = ey - arrow_size * (uy * cos_a + ux * sin_a)
    draw.polygon(
        [(ex, ey), (left_x, left_y), (right_x, right_y)],
        fill=color,
        outline=color,
    )


def _get_port_position(node, port_id, image_width, image_height):
    for port in node.get("ports", []):
        if port.get("id") == port_id:
            pos = port.get("position", [])
            if pos and len(pos) == 2:
                return denormalize_coordinates(pos, image_width, image_height)
    return None


def _get_node_center(node, image_width, image_height):
    position = node.get("position", [])
    if position and len(position) == 2:
        return denormalize_coordinates(position, image_width, image_height)
    bbox = node.get("bbox", [])
    if bbox and len(bbox) == 4:
        pixel_bbox = denormalize_coordinates(bbox, image_width, image_height)
        cx = (pixel_bbox[0] + pixel_bbox[2]) // 2
        cy = (pixel_bbox[1] + pixel_bbox[3]) // 2
        return [cx, cy]
    return None


def _get_node_display_label(node):
    node_type = node.get('node_type', '')
    if node_type == 'boundary':
        parts = []
        drawing_id = node.get('drawing_id', '')
        equipment_tags = node.get('equipment_tag', [])
        description = node.get('description', '')
        if drawing_id:
            parts.append(drawing_id)
        if equipment_tags:
            parts.append(','.join(equipment_tags))
        if description and not parts:
            parts.append(description)
        return ' '.join(parts) if parts else node.get('label', node.get('name', ''))
    return node.get('label', node.get('name', ''))


def get_color_by_type(node_type):
    colors = {
        'equipment': '#FF0000',
        'instrument': '#FF0000',
        'split': '#0000FF',
        'merge': '#0000FF',
        'elbow': '#0000FF',
        'boundary': '#0000FF',
        'stream': '#FF0000',
        'valve': '#FF0000',
        'pipe': '#FF0000',
    }
    return colors.get(node_type, '#0000FF')


def draw_edges(draw, edges, nodes, image_width, image_height, color='#FF0000', line_width=3):
    for edge_id, edge in edges.items():
        source_node_id = edge.get('source_node_id', '')
        target_node_id = edge.get('target_node_id', '')
        source_port_id = edge.get('source_port_id', '')
        target_port_id = edge.get('target_port_id', '')

        source_node = nodes.get(source_node_id)
        target_node = nodes.get(target_node_id)

        if not source_node or not target_node:
            continue

        start = None
        end = None

        if source_port_id:
            start = _get_port_position(source_node, source_port_id, image_width, image_height)
        if not start:
            start = _get_node_center(source_node, image_width, image_height)

        if target_port_id:
            end = _get_port_position(target_node, target_port_id, image_width, image_height)
        if not end:
            end = _get_node_center(target_node, image_width, image_height)

        if not start or not end:
            continue

        draw_arrow(draw, start, end, color=color, line_width=line_width)

        stream_number = edge.get('stream_number', '')
        if stream_number:
            font = get_chinese_font(10)
            mid_x = (start[0] + end[0]) // 2
            mid_y = (start[1] + end[1]) // 2
            draw.text((mid_x, mid_y - 10), stream_number, fill=color, font=font)


PFD_LEGEND_ITEMS = [
    ("设备bbox", '#FF0000', "rect"),
    ("虚拟节点bbox", '#0000FF', "rect"),
    ("INPUT端口", PORT_DIRECTION_COLORS["input"], "circle"),
    ("OUTPUT端口", PORT_DIRECTION_COLORS["output"], "circle"),
    ("UNKNOWN端口", PORT_DIRECTION_COLORS["unknown"], "circle"),
    ("UTILITY端口", PORT_CATEGORY_COLORS["utility"], "circle"),
    ("设备中心", EQUIPMENT_CENTER_COLOR, "circle"),
    ("虚拟节点中心", VIRTUAL_NODE_CENTER_COLOR, "circle"),
    ("连线", '#FF0000', "arrow"),
]


def draw_legend(draw, image_width, image_height, items):
    legend_height = max(int(image_height / 25), 30)
    padding_h = int(legend_height / 3)
    font_size = int(legend_height * 0.6)
    font = get_chinese_font(font_size)

    symbol_size = int(legend_height * 0.5)
    symbol_text_gap = int(legend_height / 4)
    item_gap = int(legend_height / 2)

    total_items_width = 0
    for item in items:
        text = item[0]
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        total_items_width += symbol_size + symbol_text_gap + text_width + item_gap
    total_items_width -= item_gap

    legend_y = image_height - legend_height

    draw.rectangle(
        [0, legend_y, image_width, image_height],
        fill="white",
        outline="black",
        width=2,
    )

    current_x = padding_h
    symbol_y = legend_y + (legend_height - symbol_size) // 2

    for item in items:
        text = item[0]
        color = item[1]
        item_type = item[2] if len(item) > 2 else "rect"

        if item_type == "rect":
            draw.rectangle(
                [current_x, symbol_y, current_x + symbol_size, symbol_y + symbol_size],
                outline=color,
                width=3,
            )
        elif item_type == "circle":
            draw.ellipse(
                [current_x, symbol_y, current_x + symbol_size, symbol_y + symbol_size],
                fill=color,
                outline=color,
            )
        elif item_type == "arrow":
            arrow_start_x = current_x
            arrow_end_x = current_x + symbol_size
            arrow_mid_y = symbol_y + symbol_size // 2
            draw.line(
                [arrow_start_x, arrow_mid_y, arrow_end_x, arrow_mid_y],
                fill=color,
                width=3,
            )
            arrow_head_size = symbol_size // 3
            draw.polygon(
                [
                    (arrow_end_x, arrow_mid_y),
                    (arrow_end_x - arrow_head_size, arrow_mid_y - arrow_head_size // 2),
                    (arrow_end_x - arrow_head_size, arrow_mid_y + arrow_head_size // 2),
                ],
                fill=color,
                outline=color,
            )

        text_x = current_x + symbol_size + symbol_text_gap
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_height = text_bbox[3] - text_bbox[1]
        text_y = legend_y + (legend_height - text_height) // 2
        draw.text((text_x, text_y), text, fill="black", font=font)
        text_width = text_bbox[2] - text_bbox[0]
        current_x += symbol_size + symbol_text_gap + text_width + item_gap


def draw_annotations_from_result(image_path, result, output_image_path=None):
    if not image_path:
        return None

    if output_image_path is None:
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_image_path = f"output_images/{base_name}_annotated.png"

    image = load_image(image_path)
    image_width, image_height = image.size
    draw = ImageDraw.Draw(image)

    pfd_drawing = result.get('pfd_drawing') or {}
    raw_nodes = pfd_drawing.get('nodes', [])
    nodes = {n.get('id', f'node_{i}'): n for i, n in enumerate(raw_nodes)}
    raw_edges = pfd_drawing.get('edges', [])
    edges = {e.get('id', f'edge_{i}'): e for i, e in enumerate(raw_edges)}

    for node_id, node in nodes.items():
        node_type = node.get('node_type', 'unknown')
        color = get_color_by_type(node_type)

        bbox = node.get('bbox', [])
        if bbox and len(bbox) == 4:
            pixel_bbox = denormalize_coordinates(bbox, image_width, image_height)
            label = _get_node_display_label(node)
            draw_bbox_with_label(draw, pixel_bbox, color, label=label, line_width=1)

        position = node.get('position', [])
        if position and len(position) == 2:
            pixel_pos = denormalize_coordinates(position, image_width, image_height)
            center_color = EQUIPMENT_CENTER_COLOR if node_type == 'equipment' else VIRTUAL_NODE_CENTER_COLOR
            draw_position_marker(draw, pixel_pos, color=center_color, radius=3)

        ports = node.get('ports', [])
        if ports:
            draw_ports_on_image(draw, ports, image_width, image_height)

    if edges:
        draw_edges(draw, edges, nodes, image_width, image_height)

    draw_legend(draw, image_width, image_height, PFD_LEGEND_ITEMS)

    image.save(output_image_path)
    return output_image_path
