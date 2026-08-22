"""Graph filtering utilities for PFD topology.

Consolidated module for all graph node filtering operations. When nodes are removed,
edges passing through them are traced and merged to create direct connections
between remaining nodes (path contraction).

Public functions:
- filter_graph_by_equipment_types: Keep only specified equipment types, merge edges
"""

from __future__ import annotations

from typing import Any, Callable


def _to_dict(data: dict | list) -> dict:
    if isinstance(data, list):
        return {item.get("id", f"item_{i}"): item for i, item in enumerate(data)}
    return data


def _build_adjacency(
    edges: dict[str, Any],
    node_ids: set[str],
) -> tuple[dict[str, list[tuple[str, dict]]], dict[str, list[tuple[str, dict]]]]:
    adj_out: dict[str, list[tuple[str, dict]]] = {nid: [] for nid in node_ids}
    adj_in: dict[str, list[tuple[str, dict]]] = {nid: [] for nid in node_ids}
    edges_dict = _to_dict(edges)
    for edge in edges_dict.values():
        src = edge.get("source_node_id")
        tgt = edge.get("target_node_id")
        if src in node_ids and tgt in node_ids:
            adj_out[src].append((tgt, edge))
            adj_in[tgt].append((src, edge))
    return adj_out, adj_in


def _trace_through_removed(
    node_id: str,
    direction: str,
    adj_out: dict[str, list],
    adj_in: dict[str, list],
    nodes: dict[str, Any],
    should_remove_fn: Callable[[dict[str, Any]], bool],
    visited: set[str] | None = None,
) -> list[tuple[str, str, list[dict]]]:
    if visited is None:
        visited = set()
    if node_id in visited:
        return []
    visited.add(node_id)

    adj = adj_out if direction == "forward" else adj_in
    results = []

    for next_id, edge in adj.get(node_id, []):
        if next_id in visited:
            continue
        next_node = nodes.get(next_id)
        if not next_node:
            continue

        if should_remove_fn(next_node):
            sub_results = _trace_through_removed(
                next_id,
                direction,
                adj_out,
                adj_in,
                nodes,
                should_remove_fn,
                visited.copy(),
            )
            for kept_id, port_id, chain in sub_results:
                new_chain = [edge] + chain if direction == "forward" else chain + [edge]
                results.append((kept_id, port_id, new_chain))
        else:
            port_id = (
                edge.get("target_port_id") if direction == "forward" else edge.get("source_port_id")
            )
            results.append((next_id, port_id, [edge]))

    return results


def _merge_edge_info(edge_chain: list[dict]) -> dict[str, Any]:
    stream_number = ""
    stream_name = ""
    medium = ""
    condition = {}
    control_info = {}

    for edge in edge_chain:
        if edge.get("stream_number"):
            stream_number = edge["stream_number"]
        if edge.get("stream_name"):
            stream_name = edge["stream_name"]
        if edge.get("medium"):
            medium = edge["medium"]
        if edge.get("condition"):
            condition = edge["condition"]
        if edge.get("control_info"):
            control_info = edge["control_info"]

    return {
        "stream_number": stream_number,
        "stream_name": stream_name,
        "medium": medium,
        "condition": condition,
        "control_info": control_info,
    }


def _reroute_cross_page_edges(
    cross_page_edges: list[dict[str, Any]],
    removed_node_ids: set[str],
    kept_nodes: dict[str, Any],
    nodes: dict[str, Any],
    adj_out: dict[str, list],
    adj_in: dict[str, list],
    should_remove_fn: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Re-route cross-page edges that reference removed boundary nodes.

    When a boundary node is removed, cross-page edges referencing it are re-routed
    to the kept equipment node(s) it was connected to via regular edges, instead
    of being dropped. Traces through chains of removed nodes (path contraction).

    Args:
        cross_page_edges: Original cross-page edge list.
        removed_node_ids: Set of node IDs that were removed.
        kept_nodes: Dict of kept node ID → node dict.
        nodes: All nodes dict (kept + removed).
        adj_out / adj_in: Adjacency maps built from all edges.
        should_remove_fn: Function to check if a node should be removed.

    Returns:
        New cross-page edge list with re-routed references.
    """
    # Build replacement mapping: removed_node_id -> [(kept_id, page_index), ...]
    replacements: dict[str, list[tuple[str, int]]] = {}
    for cp_edge in cross_page_edges:
        for endpoint, direction in (
            ("from_node_id", "backward"),
            ("to_node_id", "forward"),
        ):
            nid = cp_edge.get(endpoint, "")
            if nid in removed_node_ids and nid not in replacements:
                traced = _trace_through_removed(
                    nid, direction, adj_out, adj_in, nodes, should_remove_fn, set()
                )
                repls = [
                    (kept_id, kept_nodes[kept_id].get("page_index", 0))
                    for kept_id, _, _ in traced
                    if kept_id in kept_nodes
                ]
                replacements[nid] = repls

    new_cross_page_edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for cp_edge in cross_page_edges:
        from_id = cp_edge.get("from_node_id", "")
        to_id = cp_edge.get("to_node_id", "")

        # Use replacements for removed nodes; keep original for kept nodes
        from_repls = replacements.get(
            from_id,
            [(from_id, cp_edge.get("from_page_index", 0))] if from_id in kept_nodes else [],
        )
        to_repls = replacements.get(
            to_id,
            [(to_id, cp_edge.get("to_page_index", 0))] if to_id in kept_nodes else [],
        )

        for new_from_id, new_from_pi in from_repls:
            for new_to_id, new_to_pi in to_repls:
                combo = (new_from_id, new_to_id)
                if combo in seen:
                    continue
                seen.add(combo)
                new_edge = dict(cp_edge)
                new_edge["from_node_id"] = new_from_id
                new_edge["from_page_index"] = new_from_pi
                new_edge["to_node_id"] = new_to_id
                new_edge["to_page_index"] = new_to_pi
                new_cross_page_edges.append(new_edge)

    return new_cross_page_edges


def _filter_graph(
    graph: dict[str, Any],
    should_remove_fn: Callable[[dict[str, Any]], bool],
    edge_id_prefix: str = "edge",
) -> dict[str, Any]:
    nodes = _to_dict(graph.get("nodes", {}))
    edges = _to_dict(graph.get("edges", {}))

    kept_nodes: dict[str, Any] = {}
    removed_node_ids: set[str] = set()

    for node_id, node in nodes.items():
        if should_remove_fn(node):
            removed_node_ids.add(node_id)
        else:
            kept_nodes[node_id] = node

    all_node_ids = set(nodes.keys())
    adj_out, adj_in = _build_adjacency(edges, all_node_ids)

    new_edges: dict[str, Any] = {}
    edge_counter = 1
    processed: set[tuple[str, str, str, str]] = set()

    for node_id in kept_nodes:
        for next_id, edge in adj_out.get(node_id, []):
            next_node = nodes.get(next_id)
            if not next_node:
                continue

            source_port = edge.get("source_port_id", "")

            if next_id in kept_nodes:
                conn_key = (node_id, next_id, source_port, edge.get("target_port_id", ""))
                if conn_key not in processed:
                    new_edges[f"{edge_id_prefix}_{edge_counter}"] = {
                        "id": f"{edge_id_prefix}_{edge_counter}",
                        "source_node_id": node_id,
                        "source_port_id": source_port,
                        "target_node_id": next_id,
                        "target_port_id": edge.get("target_port_id", ""),
                        "stream_number": edge.get("stream_number", ""),
                        "stream_name": edge.get("stream_name", ""),
                        "medium": edge.get("medium", ""),
                        "condition": edge.get("condition", {}),
                        "control_info": edge.get("control_info", {}),
                        "metadata": edge.get("metadata", {}),
                        "page_index": edge.get("page_index"),
                        "source_node_pageindex": edge.get("source_node_pageindex"),
                        "target_node_pageindex": edge.get("target_node_pageindex"),
                        "waypoints": edge.get("waypoints", []),
                    }
                    processed.add(conn_key)
                    edge_counter += 1
            else:
                traced = _trace_through_removed(
                    next_id,
                    "forward",
                    adj_out,
                    adj_in,
                    nodes,
                    should_remove_fn,
                    {node_id},
                )
                for kept_id, target_port, chain in traced:
                    if kept_id not in kept_nodes:
                        continue
                    if kept_id == node_id:
                        continue

                    full_chain = [edge] + chain
                    conn_key = (node_id, kept_id, source_port, target_port)
                    if conn_key in processed:
                        continue

                    merged = _merge_edge_info(full_chain)
                    removed_intermediates = sorted(
                        {
                            eid
                            for e in full_chain
                            for eid in (
                                e.get("source_node_id", ""),
                                e.get("target_node_id", ""),
                            )
                            if eid in removed_node_ids
                        }
                    )

                    new_edges[f"{edge_id_prefix}_{edge_counter}"] = {
                        "id": f"{edge_id_prefix}_{edge_counter}",
                        "source_node_id": node_id,
                        "source_port_id": source_port,
                        "target_node_id": kept_id,
                        "target_port_id": target_port,
                        **merged,
                        "page_index": full_chain[0].get("page_index"),
                        "source_node_pageindex": full_chain[0].get("source_node_pageindex"),
                        "target_node_pageindex": full_chain[-1].get("target_node_pageindex"),
                        "waypoints": [],
                        "metadata": {
                            "filtered": True,
                            "original_edge_count": len(full_chain),
                            "removed_intermediate_nodes": removed_intermediates,
                        },
                    }
                    processed.add(conn_key)
                    edge_counter += 1

    new_node_index: dict[str, Any] = {}
    for key, node_ids in graph.get("node_index", {}).items():
        filtered_ids = [nid for nid in node_ids if nid in kept_nodes]
        if filtered_ids:
            new_node_index[key] = filtered_ids

    new_cross_page_edges = _reroute_cross_page_edges(
        graph.get("cross_page_edges", []),
        removed_node_ids,
        kept_nodes,
        nodes,
        adj_out,
        adj_in,
        should_remove_fn,
    )

    result: dict[str, Any] = {}
    for key in graph:
        if key == "nodes":
            result["nodes"] = list(kept_nodes.values())
        elif key == "edges":
            result["edges"] = list(new_edges.values())
        elif key == "node_index":
            result["node_index"] = new_node_index
        elif key == "cross_page_edges":
            result["cross_page_edges"] = new_cross_page_edges
        else:
            result[key] = graph[key]

    return result


def filter_graph_by_equipment_types(
    graph: dict[str, Any],
    kept_equipment_types: set[str] | list[str],
    keep_boundary_nodes: bool = True,
) -> dict[str, Any]:
    """Filter a global graph by keeping only specified equipment types.

    Removes equipment nodes whose equipment_type is not in kept_equipment_types,
    while preserving connectivity by creating direct edges between kept nodes
    that were previously connected through removed nodes (path contraction).

    Example:
        If the original path is: Reactor → Pump → Cooler → Vessel
        and only {"reactor", "vessel"} are kept, the result is: Reactor → Vessel

    Args:
        graph: The global graph dict with 'nodes', 'edges', etc.
        kept_equipment_types: Set or list of equipment_type values to keep.
        keep_boundary_nodes: Whether to keep boundary (boundary_in/boundary_out) nodes.
            Defaults to True since boundary nodes represent system I/O.

    Returns:
        Filtered graph dict with the same top-level structure.
    """
    if isinstance(kept_equipment_types, list):
        kept_equipment_types = set(kept_equipment_types)

    def should_remove(node: dict[str, Any]) -> bool:
        node_type = node.get("node_type", "")
        if node_type == "equipment":
            return node.get("equipment_type", "") not in kept_equipment_types
        if node_type == "boundary":
            return not keep_boundary_nodes
        # Remove all other auxiliary types (keypoint, instrument, etc.)
        return True

    return _filter_graph(graph, should_remove, edge_id_prefix="filtered_edge")
