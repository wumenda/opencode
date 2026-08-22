"""Cross-page edge generation for multi-page PFD extraction.

Generates cross-page edges by matching cross_drawing boundary nodes to equipment
nodes on other pages via equipment_tag. Also builds a global graph with page-aware
node ids (page_index prefixed) so that same-id nodes from different pages are
distinguishable.

Public functions:
- generate_cross_page_edges: Generate cross-page StreamEdges from all pages' nodes
- build_global_graph: Build a GlobalPFDGraph with page-aware ids from page results
"""

from __future__ import annotations

import re
from typing import Any, Optional

from src.core import get_logger

logger = get_logger(__name__)

# Boundary types that participate in cross-page matching
_CROSS_DRAWING_OUT = "cross_drawing_out"
_CROSS_DRAWING_IN = "cross_drawing_in"


def _page_aware_id(page_index: int, node_id: str) -> str:
    """Build a page-aware node id by prefixing page_index."""
    return f"p{page_index}_{node_id}"


def _normalize_tag(tag: str) -> str:
    """Normalize equipment tag for matching.

    Consistent with topology_overlay._normalize_tag: strip spaces, hyphens,
    underscores, slashes and normalize to uppercase so that "V-81001",
    "V_81001" and "V81001" all match.
    """
    return re.sub(r"[\s\-_/]", "", tag.strip()).upper()


def _build_equipment_tag_index(
    all_nodes: list[dict[str, Any]],
) -> dict[str, list[tuple[str, int]]]:
    """Build an index from normalized tag -> [(node_id, page_index), ...].

    Only indexes equipment nodes that have a non-empty tag.
    """
    index: dict[str, list[tuple[str, int]]] = {}
    for node in all_nodes:
        if node.get("node_type") != "equipment":
            continue
        tag = str(node.get("tag", "")).strip()
        if not tag:
            continue
        page_index = node.get("page_index")
        if page_index is None:
            continue
        norm_tag = _normalize_tag(tag)
        index.setdefault(norm_tag, []).append((node["id"], page_index))
    return index


def _pick_port_id(node: dict[str, Any], direction: str) -> str:
    """Return the id of the first port with the given direction, or '' if none.

    Args:
        node: Node dict that may contain a "ports" list.
        direction: "input" or "output".
    """
    for port in node.get("ports", []):
        port_dir = port.get("direction", "")
        if isinstance(port_dir, str) and port_dir.lower() == direction:
            return port.get("id", "")
    return ""


def generate_cross_page_edges(
    all_nodes: list[dict[str, Any]],
    page_drawing_id_map: Optional[dict[str, list[int]]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate cross-page edges by matching boundary nodes to equipment nodes.

    Matching rules:
    - cross_drawing_out boundary node (page A) with equipment_tag T:
      matches equipment node with tag T on page B (B != A).
      Edge direction: boundary_node(A) -> equipment_node(B)
      match_method: equipment_tag_dest
    - cross_drawing_in boundary node (page A) with equipment_tag T:
      matches equipment node with tag T on page B (B != A).
      Edge direction: equipment_node(B) -> boundary_node(A)
      match_method: equipment_tag_source

    Matching scope (drawing_id-directed):
    - If boundary node carries a non-empty drawing_id AND that drawing_id exists
      in page_drawing_id_map (i.e. DrawingInfoExpert extracted the same drawing_id
      for some page), restrict candidate search to those pages (directed mode).
    - Otherwise (drawing_id empty, or no page has that drawing_id — format
      mismatch), fall back to global search across all pages (exclude same page).

    In directed mode, if no candidate found on the targeted page(s), the search
    falls back to global to avoid missing cross-page links.

    Args:
        all_nodes: All nodes from all pages, each with page_index field.
        page_drawing_id_map: Mapping from drawing_id (from DrawingInfoExpert) to
            list of page_indexes that carry that drawing_id. Used to direct the
            cross-page equipment search. None or empty disables directed mode.

    Returns:
        Tuple of (cross_page_edges, cross_page_links, unresolved_links) where:
        - cross_page_edges: list of StreamEdge dicts with page-aware ids and
          source_node_pageindex/target_node_pageindex set
        - cross_page_links: list of CrossPageLink dicts (metadata)
        - unresolved_links: list of UnresolvedCrossDrawingLink dicts for boundary
          nodes whose equipment_tags could not be matched on other pages
    """
    tag_index = _build_equipment_tag_index(all_nodes)
    node_by_id: dict[str, dict[str, Any]] = {
        n["id"]: n for n in all_nodes if n.get("id")
    }
    cross_page_edges: list[dict[str, Any]] = []
    cross_page_links: list[dict[str, Any]] = []
    unresolved_links: list[dict[str, Any]] = []
    edge_counter = 0
    scope_counts: dict[str, int] = {"directed": 0, "global_fallback": 0, "global": 0}

    for node in all_nodes:
        if node.get("node_type") != "boundary":
            continue
        boundary_type = node.get("boundary_type", "")
        if boundary_type not in (_CROSS_DRAWING_OUT, _CROSS_DRAWING_IN):
            continue

        page_index = node.get("page_index")
        if page_index is None:
            continue

        raw_tags = node.get("equipment_tag", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags] if raw_tags.strip() else []
        equipment_tags = raw_tags
        node_id = node["id"]
        drawing_id = node.get("drawing_id", "")
        description = node.get("description", "")
        label = node.get("label", "")

        if not equipment_tags:
            # cross_drawing 边界节点缺少 equipment_tag，无法匹配，记录为未解析
            unresolved_links.append({
                "node_id": node_id,
                "page_index": page_index,
                "boundary_type": boundary_type,
                "equipment_tags": [],
                "unresolved_tags": [],
                "description": f"cross_drawing boundary node without equipment_tag (label={label})",
            })
            continue

        unresolved_tags: list[str] = []
        matched = False

        for tag in equipment_tags:
            norm_tag = _normalize_tag(tag)
            all_matches = tag_index.get(norm_tag, [])
            # Exclude same-page matches
            all_matches = [(eid, pidx) for eid, pidx in all_matches if pidx != page_index]

            # Drawing_id-directed search: restrict to pages whose drawing_id
            # matches the boundary node's drawing_id (from DrawingInfoExpert).
            match_scope = "global"
            candidates = all_matches
            if drawing_id and page_drawing_id_map:
                directed_pages = set(page_drawing_id_map.get(drawing_id, []))
                if directed_pages:
                    directed = [
                        (eid, pidx) for eid, pidx in all_matches if pidx in directed_pages
                    ]
                    if directed:
                        candidates = directed
                        match_scope = "directed"
                    else:
                        # Directed target page(s) exist but no equipment found
                        # there → fall back to global to avoid missing links
                        match_scope = "global_fallback"

            if not candidates:
                logger.debug(
                    f"Cross-page match not found: boundary '{node_id}' "
                    f"(page {page_index}, tag={tag}, type={boundary_type}, "
                    f"scope={match_scope})"
                )
                unresolved_tags.append(tag)
                continue

            matched = True
            for equip_id, equip_page_index in candidates:
                edge_counter += 1
                edge_id = f"cross_stitch_{edge_counter}"

                if boundary_type == _CROSS_DRAWING_OUT:
                    # boundary(out) -> equipment(dest page)
                    source_id = node_id
                    target_id = equip_id
                    source_page = page_index
                    target_page = equip_page_index
                    match_method = "equipment_tag_dest"
                    stream_name = description or label
                    # 跨图纸出料节点的输出端口 -> 下游目标设备的输入端口
                    source_port_id = _pick_port_id(node, "output")
                    target_port_id = _pick_port_id(node_by_id.get(equip_id, {}), "input")
                else:
                    # equipment(source page) -> boundary(in)
                    source_id = equip_id
                    target_id = node_id
                    source_page = equip_page_index
                    target_page = page_index
                    match_method = "equipment_tag_source"
                    stream_name = description or label
                    # 源设备的输出端口 -> 跨图纸进料节点的输入端口
                    source_port_id = _pick_port_id(node_by_id.get(equip_id, {}), "output")
                    target_port_id = _pick_port_id(node, "input")

                edge_dict = {
                    "id": edge_id,
                    "source_node_id": source_id,
                    "source_port_id": source_port_id,
                    "target_node_id": target_id,
                    "target_port_id": target_port_id,
                    "stream_number": "",
                    "stream_name": stream_name,
                    "medium": "",
                    "condition": {},
                    "control_info": {},
                    "metadata": {
                        "cross_page_link": True,
                        "from_page": source_page,
                        "to_page": target_page,
                        "from_drawing_id": drawing_id if boundary_type == _CROSS_DRAWING_IN else "",
                        "to_drawing_id": drawing_id if boundary_type == _CROSS_DRAWING_OUT else "",
                        "match_method": match_method,
                        "match_scope": match_scope,
                        "equipment_tag": tag,
                    },
                    "page_index": None,
                    "source_node_pageindex": source_page,
                    "target_node_pageindex": target_page,
                }
                cross_page_edges.append(edge_dict)
                scope_counts[match_scope] = scope_counts.get(match_scope, 0) + 1

                link_dict = {
                    "from_node_id": source_id,
                    "from_page_index": source_page,
                    "to_node_id": target_id,
                    "to_page_index": target_page,
                    "link_type": "cross_page_stitch",
                    "status": "accept",
                    "match_reason": f"{match_method}:{tag}",
                }
                cross_page_links.append(link_dict)

        # 该边界节点的所有 tag 都未匹配，或部分 tag 未匹配 → 记录未解析
        if unresolved_tags:
            unresolved_links.append({
                "node_id": node_id,
                "page_index": page_index,
                "boundary_type": boundary_type,
                "equipment_tags": list(equipment_tags),
                "unresolved_tags": unresolved_tags,
                "description": (
                    "fully unresolved" if not matched else "partially unresolved"
                ) + f" (label={label})",
            })

    logger.info(
        f"Cross-page edge generation: {len(cross_page_edges)} edges, "
        f"{len(cross_page_links)} links "
        f"(directed={scope_counts.get('directed', 0)}, "
        f"global_fallback={scope_counts.get('global_fallback', 0)}, "
        f"global={scope_counts.get('global', 0)}), "
        f"{len(unresolved_links)} unresolved boundary nodes"
    )
    return cross_page_edges, cross_page_links, unresolved_links


def build_global_graph(
    page_graphs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a global graph dict with page-aware node ids from page results.

    Args:
        page_graphs: List of page graph dicts, each containing:
            - page_index: int
            - pfd_drawing: {nodes: [...], edges: [...]}

    Returns:
        Global graph dict with:
        - nodes: all nodes with page-aware ids
        - edges: all in-page edges (page-aware ids) + cross-page edges
        - cross_page_edges: list of CrossPageLink dicts
        - node_index: tag -> [page-aware node ids]
    """
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    node_id_map: dict[tuple[int, str], str] = {}  # (page_index, original_id) -> page_aware_id
    # drawing_id (from DrawingInfoExpert, page-level) -> [page_index, ...]
    page_drawing_id_map: dict[str, list[int]] = {}

    # Collect all nodes and edges, build id mapping
    for pg in page_graphs:
        page_index = pg.get("page_index", 0)
        drawing = pg.get("pfd_drawing", {})
        # Page-level drawing_id (from DrawingInfoExpert via PFDDrawing metadata)
        page_drawing_id = str(drawing.get("drawing_id", "")).strip()
        if page_drawing_id:
            page_drawing_id_map.setdefault(page_drawing_id, []).append(page_index)
        edges = drawing.get("edges", [])
        # pfd_drawing 可能是 {nodes, edges}（PFDDrawing 模型）或
        # {equipment_nodes, boundary_nodes, edges}（前端审核结构）两种形式
        nodes = drawing.get("nodes", [])
        if not nodes:
            # pfd_drawing 为前端审核结构（equipment_nodes + boundary_nodes），
            # 缺少 node_type 字段，需补上以供 generate_cross_page_edges 识别
            equip_nodes = drawing.get("equipment_nodes", []) or []
            bnd_nodes = drawing.get("boundary_nodes", []) or []
            for n in equip_nodes:
                n.setdefault("node_type", "equipment")
            for n in bnd_nodes:
                n.setdefault("node_type", "boundary")
            nodes = equip_nodes + bnd_nodes

        for node in nodes:
            original_id = node.get("id", "")
            if not original_id:
                continue
            page_aware_id = _page_aware_id(page_index, original_id)
            node_id_map[(page_index, original_id)] = page_aware_id

            # Create node with page-aware id
            new_node = dict(node)
            new_node["id"] = page_aware_id
            new_node["page_index"] = page_index
            # Update ports' parent_node_id
            new_ports = []
            for port in new_node.get("ports", []):
                new_port = dict(port)
                port_id = new_port.get("id", "")
                if port_id:
                    new_port["id"] = _page_aware_id(page_index, port_id)
                new_port["parent_node_id"] = page_aware_id
                new_ports.append(new_port)
            new_node["ports"] = new_ports
            all_nodes.append(new_node)

        for edge in edges:
            original_id = edge.get("id", "")
            if not original_id:
                continue
            source_id = edge.get("source_node_id", "")
            target_id = edge.get("target_node_id", "")

            new_edge = dict(edge)
            new_edge["id"] = _page_aware_id(page_index, original_id)
            if source_id:
                new_edge["source_node_id"] = _page_aware_id(page_index, source_id)
            if target_id:
                new_edge["target_node_id"] = _page_aware_id(page_index, target_id)
            # Update port ids
            source_port = new_edge.get("source_port_id", "")
            target_port = new_edge.get("target_port_id", "")
            if source_port:
                new_edge["source_port_id"] = _page_aware_id(page_index, source_port)
            if target_port:
                new_edge["target_port_id"] = _page_aware_id(page_index, target_port)
            # Set page index fields for in-page edges
            new_edge["page_index"] = page_index
            new_edge["source_node_pageindex"] = page_index
            new_edge["target_node_pageindex"] = page_index
            all_edges.append(new_edge)

    # Generate cross-page edges (drawing_id-directed where possible)
    cross_page_edges, cross_page_links, unresolved_links = generate_cross_page_edges(
        all_nodes, page_drawing_id_map=page_drawing_id_map or None
    )
    all_edges.extend(cross_page_edges)

    # Build node_index: tag -> [page-aware node ids]
    node_index: dict[str, list[str]] = {}
    for node in all_nodes:
        if node.get("node_type") == "equipment":
            tag = str(node.get("tag", "")).strip()
            if tag:
                node_index.setdefault(tag, []).append(node["id"])

    return {
        "nodes": all_nodes,
        "edges": all_edges,
        "cross_page_edges": cross_page_links,
        "unresolved_links": unresolved_links,
        "node_index": node_index,
    }
