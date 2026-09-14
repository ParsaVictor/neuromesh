//! Package-based graph snapshot sharding for monorepos.
//!
//! When a single `graph.bin` would exceed `max_graph_bytes`, nodes/edges are
//! grouped by package directory (`crates/<name>`, `apps/<name>`, `src`) and
//! written to `graph_shards/<slug>.bin`. The main file keeps metadata plus a
//! manifest so load can reassemble one logical graph.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use neuromesh_core::{ContextEdge, ContextNode, NodeId};

/// Stable package slug from a workspace-relative path.
pub fn package_slug(path: &str) -> String {
    let p = path.replace('\\', "/");
    let parts: Vec<&str> = p
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .collect();
    if parts.len() >= 2 && matches!(parts[0], "crates" | "apps" | "packages" | "libs") {
        return sanitize_slug(parts[1]);
    }
    if parts.first().copied() == Some("src") {
        return "src".to_string();
    }
    if let Some(first) = parts.first() {
        return sanitize_slug(first);
    }
    "_root".to_string()
}

fn sanitize_slug(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
            out.push(c.to_ascii_lowercase());
        } else {
            out.push('_');
        }
    }
    if out.is_empty() {
        "_root".to_string()
    } else {
        out
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphNodeShard {
    pub version: u32,
    pub slug: String,
    pub nodes: Vec<ContextNode>,
    pub edges: Vec<ContextEdge>,
}

pub fn shards_dir(graph_bin: &Path) -> PathBuf {
    graph_bin
        .parent()
        .map(|p| p.join("graph_shards"))
        .unwrap_or_else(|| PathBuf::from("graph_shards"))
}

pub fn shard_path(graph_bin: &Path, slug: &str) -> PathBuf {
    shards_dir(graph_bin).join(format!("{slug}.bin"))
}

/// Split nodes/edges into package groups. Edge ownership follows the source node's file.
pub fn split_by_package(
    nodes: Vec<ContextNode>,
    edges: Vec<ContextEdge>,
) -> BTreeMap<String, (Vec<ContextNode>, Vec<ContextEdge>)> {
    let file_of: HashMap<NodeId, String> = nodes
        .iter()
        .map(|n| (n.id.clone(), n.file_path.to_string_lossy().to_string()))
        .collect();
    let mut groups: BTreeMap<String, (Vec<ContextNode>, Vec<ContextEdge>)> = BTreeMap::new();
    for node in nodes {
        let path = node.file_path.to_string_lossy();
        let slug = package_slug(&path);
        groups.entry(slug).or_default().0.push(node);
    }
    for edge in edges {
        let path = file_of.get(&edge.source).cloned().unwrap_or_default();
        let slug = if path.is_empty() {
            groups
                .keys()
                .next()
                .cloned()
                .unwrap_or_else(|| "_root".to_string())
        } else {
            package_slug(&path)
        };
        groups.entry(slug).or_default().1.push(edge);
    }
    groups
}

pub fn merge_shards(
    parts: impl IntoIterator<Item = GraphNodeShard>,
) -> (Vec<ContextNode>, Vec<ContextEdge>) {
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let mut seen: HashMap<String, usize> = HashMap::new();
    for part in parts {
        for n in part.nodes {
            let key = n.id.0.to_string();
            if let Some(&idx) = seen.get(&key) {
                nodes[idx] = n;
            } else {
                seen.insert(key, nodes.len());
                nodes.push(n);
            }
        }
        edges.extend(part.edges);
    }
    (nodes, edges)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use neuromesh_core::{EdgeId, EdgeType, NodeType, ProjectId};

    fn node(id: &str, path: &str) -> ContextNode {
        ContextNode {
            id: NodeId(id.into()),
            project_id: ProjectId::new("t"),
            file_path: PathBuf::from(path),
            node_type: NodeType::Function,
            name: id.into(),
            signature: None,
            doc_summary: None,
            line_range: None,
            token_cost: 1,
            content: None,
            content_hash: String::new(),
            parent: None,
            base_relevance: 0.0,
            access_count: 0,
            last_accessed: Utc::now(),
        }
    }

    #[test]
    fn package_slug_from_crates() {
        assert_eq!(
            package_slug("crates/neuromesh-mcp/src/lib.rs"),
            "neuromesh-mcp"
        );
        assert_eq!(package_slug("apps/web/main.ts"), "web");
        assert_eq!(package_slug("src/lib.rs"), "src");
        assert_eq!(package_slug(r"crates\foo\bar.rs"), "foo");
    }

    #[test]
    fn split_and_merge_roundtrip() {
        let nodes = vec![
            node("a", "crates/a/src/lib.rs"),
            node("b", "crates/b/src/lib.rs"),
            node("c", "src/main.rs"),
        ];
        let edges = vec![ContextEdge {
            id: EdgeId("e1".into()),
            project_id: ProjectId::new("t"),
            source: NodeId("a".into()),
            target: NodeId("b".into()),
            edge_type: EdgeType::Imports,
            pheromone_weight: 0.5,
            reinforcement_count: 0,
            failure_count: 0,
            last_reinforced: Utc::now(),
            confidence: Default::default(),
        }];
        let groups = split_by_package(nodes, edges);
        assert!(groups.contains_key("a"));
        assert!(groups.contains_key("b"));
        assert!(groups.contains_key("src"));
        let parts: Vec<GraphNodeShard> = groups
            .into_iter()
            .map(|(slug, (nodes, edges))| GraphNodeShard {
                version: 3,
                slug,
                nodes,
                edges,
            })
            .collect();
        let (nodes, edges) = merge_shards(parts);
        assert_eq!(nodes.len(), 3);
        assert_eq!(edges.len(), 1);
    }
}
