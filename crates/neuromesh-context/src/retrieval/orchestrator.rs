use crate::activator::ContextActivator;
use crate::retrieval::budget::RetrievalBudget;
use crate::retrieval::escalate::{run_incremental, EscalationResult};
use crate::retrieval::sufficiency::SufficiencyEstimator;
use neuromesh_core::{ContextView, OptimizationMode, RetrievalMetadata, TaskSignature};
use neuromesh_graph::NeuralProjectGraph;

#[derive(Default)]
pub struct RetrievalOrchestrator {
    budget: RetrievalBudget,
    estimator: SufficiencyEstimator,
}

impl RetrievalOrchestrator {
    pub fn new(budget: RetrievalBudget) -> Self {
        Self {
            budget,
            estimator: SufficiencyEstimator::default(),
        }
    }

    /// Single-pass incremental L1→L2→L3 with critical-gap-only escalation.
    pub fn run(
        &self,
        activator: &ContextActivator,
        graph: &NeuralProjectGraph,
        signature: &TaskSignature,
        mode: OptimizationMode,
    ) -> ContextView {
        #[cfg(feature = "embeddings")]
        neuromesh_embed::packet_cache_begin();
        let view = self.run_inner(activator, graph, signature, mode);
        #[cfg(feature = "embeddings")]
        neuromesh_embed::packet_cache_end();
        view
    }

    fn run_inner(
        &self,
        activator: &ContextActivator,
        graph: &NeuralProjectGraph,
        signature: &TaskSignature,
        mode: OptimizationMode,
    ) -> ContextView {
        let EscalationResult {
            mut view,
            final_tier,
            levels_attempted,
            latency_ms,
            estimate: est,
        } = run_incremental(
            activator,
            graph,
            signature,
            mode,
            &self.budget,
            &self.estimator,
        );

        enforce_no_full_workspace(&mut view, graph);

        let next_action = suggest_next_action(&est, &view);
        let suggested_keywords = if matches!(est.claim.as_str(), "partial" | "insufficient") {
            Some(suggest_keywords(signature, &view))
        } else {
            None
        };

        // B.3: high sufficiency on a coincidental hit is not a confident hit.
        // Apply even when a leftover embedding sidecar is present — a lexical
        // L1_exact + zero path overlap is still a coincidental match.
        let mut confidence = est.confidence;
        {
            let prompt = signature.raw_prompt.as_str();
            let mut best_overlap = 0.0f32;
            for n in &view.active_nodes {
                if n.node.node_type != neuromesh_core::NodeType::File {
                    continue;
                }
                let path = n.node.file_path.to_string_lossy();
                let ov = crate::retrieval::alias::path_stem_overlap(&path, prompt);
                if ov > best_overlap {
                    best_overlap = ov;
                }
            }
            let hint = crate::retrieval::alias::lexical_confidence_hint(&est.claim, est.score);
            let max_embed =
                crate::retrieval::embedding_confidence::max_embedding_score_from_seeds(&view.seeds)
                    .unwrap_or(0.0);
            let strong_embed = max_embed >= 0.45;
            let lexical_claim = matches!(
                est.claim.as_str(),
                "bounded" | "no_recorded_gap" | "partial" | "likely_sufficient"
            );
            if lexical_claim && best_overlap <= 0.0 && !strong_embed {
                confidence = confidence.min(hint).min(0.45);
                if matches!(
                    est.claim.as_str(),
                    "bounded" | "no_recorded_gap" | "likely_sufficient"
                ) {
                    confidence = confidence.min(0.40);
                }
            } else if lexical_claim && best_overlap < 0.34 && est.score < 0.5 && !strong_embed {
                confidence = confidence.min(hint);
            } else if !strong_embed {
                confidence = (confidence.min(1.0)).max(hint * 0.85).min(1.0);
            }
        }

        view.retrieval = Some(RetrievalMetadata {
            retrieval_level: final_tier.as_str().to_string(),
            sufficiency_score: est.score,
            confidence,
            claim: est.claim.clone(),
            levels_attempted,
            latency_ms,
            full_workspace_fallback: false,
            critical_gaps: est.critical_gaps.clone(),
            non_critical_gaps: est.non_critical_gaps.clone(),
            eligible_for_early_exit: est.eligible_for_early_exit,
            next_action,
            suggested_keywords,
            embedding_used: view.embedding_used,
            resolution_tier: crate::retrieval::embedding_confidence::dominant_resolution_tier(
                &view.seeds,
            ),
            max_embedding_score:
                crate::retrieval::embedding_confidence::max_embedding_score_from_seeds(&view.seeds),
            cache_hit: false,
            ort_session_active: ort_session_active(),
        });
        // Surface a low-confidence success-shaped packet as no_confident_match
        // so agents (and `neuromesh usage`) do not treat a coincidental bounded
        // hit as ground truth. Coverage.claim is what most clients and the
        // telemetry table actually display.
        let mut force_no_confident = false;
        if let Some(meta) = view.retrieval.as_ref() {
            force_no_confident = meta.confidence < 0.5
                && matches!(
                    meta.claim.as_str(),
                    "likely_sufficient" | "bounded" | "no_recorded_gap" | "partial"
                )
                && meta.max_embedding_score.unwrap_or(0.0) < 0.45;
        }
        if force_no_confident {
            if let Some(meta) = view.retrieval.as_mut() {
                meta.resolution_tier = Some("no_confident_match".into());
                meta.claim = "no_confident_match".into();
                if meta.next_action.is_none() {
                    meta.next_action = Some("neuromesh_search_symbols".into());
                }
            }
            if let Some(cov) = view.coverage.as_mut() {
                cov.claim = "no_confident_match".into();
            }
        }

        view
    }
}

/// Hard ban: selected tokens must stay below workspace tokens.
fn enforce_no_full_workspace(view: &mut ContextView, graph: &NeuralProjectGraph) {
    let workspace = graph.total_tokens().max(1);
    const MIN_WORKSPACE_FOR_BAN: usize = 256;
    if workspace < MIN_WORKSPACE_FOR_BAN {
        return;
    }

    if view.active_tokens >= workspace {
        view.active_nodes.retain(|n| {
            n.activation_score >= 0.8
                || n.expansion_reason
                    .as_deref()
                    .is_some_and(|r| r.contains("seed"))
        });
        view.active_tokens = view.active_nodes.iter().map(|n| n.node.token_cost).sum();
    }

    if view.active_tokens >= workspace {
        let mut nodes = std::mem::take(&mut view.active_nodes);
        nodes.sort_by(|a, b| {
            b.activation_score
                .partial_cmp(&a.activation_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut kept = Vec::new();
        let mut sum = 0usize;
        for n in nodes {
            if sum + n.node.token_cost < workspace {
                sum += n.node.token_cost;
                kept.push(n);
            }
        }
        view.active_nodes = kept;
        view.active_tokens = sum;
    }

    debug_assert!(
        view.active_tokens < workspace,
        "full-workspace fallback forbidden"
    );
}

fn suggest_next_action(
    est: &crate::retrieval::sufficiency::SufficiencyEstimate,
    view: &ContextView,
) -> Option<String> {
    if est.eligible_for_early_exit {
        return None;
    }
    if !est.critical_gaps.is_empty() {
        return Some("neuromesh_expand_gap".into());
    }
    if view
        .coverage
        .as_ref()
        .is_some_and(|c| c.claim == "no_seed_resolved")
    {
        return Some("neuromesh_search_symbols".into());
    }
    if est.claim == "partial" {
        return Some("neuromesh_search_symbols".into());
    }
    None
}

fn suggest_keywords(signature: &TaskSignature, view: &ContextView) -> Vec<String> {
    let mut out: Vec<String> = signature
        .identifiers
        .iter()
        .chain(signature.client_keywords.iter())
        .cloned()
        .collect();
    if let Some(coverage) = view.coverage.as_ref() {
        for gap in &coverage.packet_gaps {
            if let Some(name) = gap.path.rsplit('/').next() {
                let stem = name.trim_end_matches(".rs").trim_end_matches(".ts");
                if stem.len() >= 3 && !out.iter().any(|k| k == stem) {
                    out.push(stem.to_string());
                }
            }
        }
    }
    out.truncate(8);
    out
}

fn ort_session_active() -> bool {
    #[cfg(feature = "embeddings")]
    {
        neuromesh_embed::Embedder::is_global_loaded()
    }
    #[cfg(not(feature = "embeddings"))]
    {
        false
    }
}
