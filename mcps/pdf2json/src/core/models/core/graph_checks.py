from __future__ import annotations

from collections import deque
from typing import Any


def bfs_reachable(adjacency: dict[str, list[str]], start: str) -> set[str]:
    visited: set[str] = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def build_adjacency_from_edges(
    edges: list[Any],
    source_attr: str = "source_node_id",
    target_attr: str = "target_node_id",
) -> dict[str, list[str]]:
    from collections import defaultdict

    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        src = getattr(edge, source_attr, None)
        tgt = getattr(edge, target_attr, None)
        if src and tgt:
            adj[src].append(tgt)
    return dict(adj)


def collect_connected_node_ids(
    edges: list[Any],
    source_attr: str = "source_node_id",
    target_attr: str = "target_node_id",
) -> set[str]:
    connected: set[str] = set()
    for edge in edges:
        src = getattr(edge, source_attr, None)
        tgt = getattr(edge, target_attr, None)
        if src:
            connected.add(src)
        if tgt:
            connected.add(tgt)
    return connected


def find_self_loop_edges(
    edges: list[Any],
) -> list[dict[str, Any]]:
    results = []
    for edge in edges:
        src = getattr(edge, "source_node_id", None)
        tgt = getattr(edge, "target_node_id", None)
        src_port = getattr(edge, "source_port_id", None)
        tgt_port = getattr(edge, "target_port_id", None)
        edge_id = getattr(edge, "id", "")
        if src == tgt and src_port and tgt_port and src_port == tgt_port:
            results.append({
                "edge_id": edge_id,
                "node_id": src,
                "source_port": src_port,
                "target_port": tgt_port,
            })
    return results


def find_duplicate_edges(
    edges: list[Any],
) -> list[dict[str, Any]]:
    from collections import defaultdict

    seen: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for edge in edges:
        edge_id = getattr(edge, "id", "")
        key = (
            getattr(edge, "source_node_id", ""),
            getattr(edge, "target_node_id", ""),
            getattr(edge, "source_port_id", ""),
            getattr(edge, "target_port_id", ""),
        )
        seen[key].append(edge_id)

    results = []
    for key, edge_ids in seen.items():
        if len(edge_ids) > 1:
            for eid in edge_ids:
                results.append({
                    "edge_id": eid,
                    "source": key[0],
                    "target": key[1],
                    "all_edge_ids": edge_ids,
                })
    return results


def find_orphan_node_ids(
    node_ids: list[str],
    edges: list[Any],
) -> list[str]:
    connected = collect_connected_node_ids(edges)
    return [nid for nid in node_ids if nid not in connected]


def find_dangling_edge_refs(
    edges: list[Any],
    valid_node_ids: set[str],
) -> list[dict[str, Any]]:
    results = []
    for edge in edges:
        edge_id = getattr(edge, "id", "")
        src = getattr(edge, "source_node_id", None)
        tgt = getattr(edge, "target_node_id", None)
        if src and src not in valid_node_ids:
            results.append({
                "edge_id": edge_id,
                "missing_type": "source",
                "missing_node_id": src,
            })
        if tgt and tgt not in valid_node_ids:
            results.append({
                "edge_id": edge_id,
                "missing_type": "target",
                "missing_node_id": tgt,
            })
    return results


def find_unreachable_from_boundary(
    node_ids: list[str],
    edges: list[Any],
    boundary_in_ids: list[str],
    boundary_out_ids: list[str],
) -> list[dict[str, Any]]:
    if not boundary_in_ids:
        return []

    adj = build_adjacency_from_edges(edges)
    all_reachable: set[str] = set()
    results = []

    for in_id in boundary_in_ids:
        reachable = bfs_reachable(adj, in_id)
        all_reachable.update(reachable)

        has_path = any(out_id in reachable for out_id in boundary_out_ids)
        if not has_path:
            results.append({
                "type": "no_path_from_boundary_in",
                "node_id": in_id,
            })

    for nid in node_ids:
        if nid not in all_reachable:
            results.append({
                "type": "unreachable_from_boundary_in",
                "node_id": nid,
            })

    return results


def find_duplicate_stream_numbers(
    edges: list[Any],
) -> list[dict[str, Any]]:
    from collections import defaultdict

    stream_to_edges: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        edge_id = getattr(edge, "id", "")
        stream_number = getattr(edge, "stream_number", None)
        if stream_number:
            stream_to_edges[stream_number].append(edge_id)

    results = []
    for stream_num, edge_ids in stream_to_edges.items():
        if len(edge_ids) > 1:
            for eid in edge_ids:
                results.append({
                    "edge_id": eid,
                    "stream_number": stream_num,
                    "all_edge_ids": edge_ids,
                })
    return results
