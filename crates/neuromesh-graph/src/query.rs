use neuromesh_core::{ContextEdge, ContextNode, EdgeType, NodeId, NodeType};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

// serde skip_serializing_if requires &String / &Vec for those field types.
#[allow(clippy::ptr_arg)]
fn is_empty_str(s: &String) -> bool {
    s.is_empty()
}

#[allow(clippy::ptr_arg)]
fn is_empty_vec<T>(v: &Vec<T>) -> bool {
    v.is_empty()
}

fn is_false(b: &bool) -> bool {
    !*b
}

fn is_zero(n: &usize) -> bool {
    *n == 0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub id: NodeId,
    pub name: String,
    pub node_type: NodeType,
    pub file_path: PathBuf,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub line_range: Option<std::ops::Range<usize>>,
    pub score: f32,
    #[serde(default, skip_serializing_if = "is_empty_str")]
    pub match_reason: String,
}

impl SearchHit {
    pub fn from_node(node: &ContextNode, score: f32, match_reason: impl Into<String>) -> Self {
        Self {
            id: node.id.clone(),
            name: node.name.clone(),
            node_type: node.node_type,
            file_path: node.file_path.clone(),
            signature: node.signature.clone(),
            line_range: node.line_range.clone(),
            score,
            match_reason: match_reason.into(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TraceDirection {
    Inbound,
    Outbound,
    Both,
}

impl TraceDirection {
    pub fn parse(value: &str) -> Self {
        match value {
            "inbound" | "callers" | "in" => Self::Inbound,
            "outbound" | "callees" | "out" => Self::Outbound,
            _ => Self::Both,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceHop {
    pub from: SearchHit,
    pub to: SearchHit,
    pub edge_type: EdgeType,
    pub depth: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceResult {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin: Option<SearchHit>,
    /// False when the origin was resolved via substring/token/path fuzzy match.
    #[serde(default = "default_origin_reliable", skip_serializing_if = "is_true")]
    pub origin_reliable: bool,
    #[serde(default, skip_serializing_if = "is_empty_vec")]
    pub hops: Vec<TraceHop>,
    #[serde(default, skip_serializing_if = "is_empty_vec")]
    pub callers: Vec<SearchHit>,
    #[serde(default, skip_serializing_if = "is_empty_vec")]
    pub callees: Vec<SearchHit>,
    /// Full hop count before max_hops truncation.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub hops_total: usize,
    #[serde(default, skip_serializing_if = "is_false")]
    pub truncated: bool,
}

fn is_true(b: &bool) -> bool {
    *b
}

fn default_origin_reliable() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArchitecturePackage {
    pub name: String,
    pub file_count: usize,
    pub symbol_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArchitectureSummary {
    pub languages: Vec<(String, usize)>,
    pub packages: Vec<ArchitecturePackage>,
    pub entry_points: Vec<SearchHit>,
    pub hotspots: Vec<SearchHit>,
    pub file_count: usize,
    pub symbol_count: usize,
    pub edge_count: usize,
    pub resolved_calls: usize,
    pub resolved_imports: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImpactResult {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin: Option<SearchHit>,
    #[serde(default, skip_serializing_if = "is_empty_vec")]
    pub affected_symbols: Vec<SearchHit>,
    #[serde(default, skip_serializing_if = "is_empty_vec")]
    pub affected_files: Vec<String>,
    pub risk: String,
    pub radius: usize,
    /// Full symbol count before max_symbols truncation.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub symbols_total: usize,
    #[serde(default, skip_serializing_if = "is_false")]
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NeighborView {
    pub node: SearchHit,
    pub edge: ContextEdge,
    pub direction: String,
}

pub fn tokenize(name: &str) -> Vec<String> {
    neuromesh_parser::tokenize_ident(name)
}

pub fn path_hint_matches(path: &std::path::Path, hint: &str) -> bool {
    let path = path
        .to_string_lossy()
        .replace('\\', "/")
        .replace('-', "_")
        .to_lowercase();
    let hint = hint.replace('\\', "/").replace('-', "_").to_lowercase();
    if hint.is_empty() {
        return false;
    }
    if path.contains(&hint) {
        return true;
    }
    hint.split([':', '/', '.'])
        .filter(|part| part.len() > 2)
        .any(|part| path.contains(part))
}
