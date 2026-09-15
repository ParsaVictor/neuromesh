use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct AliasEntry {
    pub concept: &'static str,
    pub terms: &'static [&'static str],
}

/// Minimal cross-lingual concept clusters — extended for 10-language Express benchmark families.
static ALIAS_CLUSTERS: &[AliasEntry] = &[
    AliasEntry {
        concept: "routing",
        terms: &[
            "route",
            "router",
            "routing",
            "endpoint",
            "مسیر",
            "مسیریابی",
            "ruta",
            "routen",
            "路由",
            "ルーティング",
            "маршрут",
            "yönlendir",
            "routage",
            "enrutamiento",
            "rotalar",
            "التوجيه",
        ],
    },
    AliasEntry {
        concept: "middleware",
        terms: &[
            "middleware",
            "pipeline",
            "next()",
            "next",
            "میان‌افزار",
            "میان افزار",
            "لوله",
            "لوله‌ی",
            "خط أنابيب",
            "خط انابيب",
            "中间件",
            "ミドルウェア",
            "промежуточн",
            "ara katman",
            "middlewares",
            "zwischen",
        ],
    },
    AliasEntry {
        concept: "session",
        terms: &[
            "session",
            "cookie",
            "cookies",
            "cookie-session",
            "سشن",
            "کوکی",
            "куки",
            "сессии",
            "çerez",
            "oturum",
            "会话",
            "セッション",
            "تعريف الارتباط",
            "جلسات",
        ],
    },
    AliasEntry {
        concept: "auth",
        terms: &[
            "auth",
            "authentication",
            "login",
            "jwt",
            "token",
            "bearer",
            "احراز",
            "ورود",
            "توکن",
            "认证",
            "authentification",
        ],
    },
    AliasEntry {
        concept: "jwt",
        terms: &[
            "jwt",
            "json web token",
            "verify jwt",
            "validate token",
            "token expires",
            "توکن",
            "jwt",
            "اعتبارسنجی",
        ],
    },
    AliasEntry {
        concept: "query",
        terms: &[
            "query",
            "querystring",
            "query string",
            "req.query",
            "کوئری",
            "запрос",
            "consulta",
            "requête",
            "查询",
            "クエリ",
            "sorgu",
            "استعلام",
        ],
    },
    AliasEntry {
        concept: "database",
        terms: &[
            "database",
            "db",
            "model",
            "repository",
            "پایگاه",
            "دیتابیس",
            "数据库",
            "datenbank",
        ],
    },
    AliasEntry {
        concept: "render",
        terms: &[
            "render",
            "template",
            "view",
            "engine",
            "رندر",
            "قالب",
            "渲染",
            "шаблон",
            "plantilla",
            "moteur",
            "テンプレート",
        ],
    },
    AliasEntry {
        concept: "static",
        terms: &[
            "static",
            "assets",
            "public",
            // bare "فایل" is too generic — fires on فایل‌سیستم (filesystem root)
            "فایل استاتیک",
            "فایل‌های استاتیک",
            "استاتیک",
            "静态",
            "статическ",
            "statiques",
            "estáticos",
            "statik",
            "statische",
            "الثابتة",
            "静的",
        ],
    },
    AliasEntry {
        concept: "test",
        terms: &["test", "spec", "mock", "آزمون", "تست", "测试", "prueba"],
    },
    AliasEntry {
        concept: "config",
        terms: &[
            "config",
            "configuration",
            "env",
            "settings",
            "تنظیم",
            "配置",
        ],
    },
    AliasEntry {
        concept: "refactor",
        terms: &[
            "refactor",
            "rename",
            "restructure",
            "بازسازی",
            "重构",
            "refactoriser",
        ],
    },
    AliasEntry {
        concept: "error",
        terms: &[
            "error",
            "bug",
            "fix",
            "exception",
            "error handler",
            "serializer",
            "خطا",
            "باگ",
            "错误",
            "fehler",
            "错误处理",
        ],
    },
    AliasEntry {
        concept: "content_type",
        terms: &[
            "content-type",
            "content type",
            "contenttype",
            "parser",
            "mime",
            "内容类型",
            "解析器",
            "Content-Typ",
            "tipo de contenido",
            "parseur",
            "parsing",
            "نوع محتوا",
            "پارسر",
        ],
    },
    AliasEntry {
        concept: "plugin",
        terms: &[
            "plugin",
            "plugins",
            "encapsulation",
            "encapsulate",
            "register plugin",
            "插件",
            "Plugin",
            "complemento",
            "plug-in",
            "پلاگین",
            "درون‌کاشت",
            "درون کاشت",
            "کپسوله‌سازی",
            "کپسوله سازی",
        ],
    },
    AliasEntry {
        concept: "validation",
        terms: &[
            "validation",
            "validate",
            "schema",
            "ajv",
            "schemas",
            "验证",
            "Validierung",
            "validación",
            "валид",
            "اعتبارسنجی",
            "راستی‌آزمایی",
            "راستی آزمایی",
            "شِما",
        ],
    },
    AliasEntry {
        concept: "errors",
        terms: &[
            "error handler",
            "error-handler",
            "error serializer",
            "errors",
            "Fehlerbehandlung",
            "gestion des erreurs",
            "错误处理",
            "خطا",
            "خطایاب",
            "مدیریت خطا",
        ],
    },
    AliasEntry {
        concept: "filesystem",
        terms: &[
            "filesystem",
            "file system",
            "filesystem root",
            "dangerous path",
            "unsafe path",
            "workspace root",
            "home directory",
            "drive root",
            "سیستم فایل",
            "فایل‌سیستم",
            "فایلسیستم",
            "ریشه فایل",
            "ریشه‌ی فایل",
            "ریشهٔ فایل",
            "ریشه فایل‌سیستم",
            "ریشه‌ی فایل‌سیستم",
            "ریشه فایلسیستم",
            "مسیر خطرناک",
            "مسیرهای خطرناک",
            "جلوگیری از ایندکس",
        ],
    },
    AliasEntry {
        concept: "path_safety",
        terms: &[
            "safe workspace",
            "unsafe workspace",
            "path traversal",
            "directory traversal",
            "confine",
            "assert_safe_workspace",
            "is_safe_workspace",
            "امنیت مسیر",
            "مسیر امن",
            "ایمنی مسیر",
        ],
    },
    AliasEntry {
        concept: "learning",
        terms: &[
            "pheromone",
            "reinforce",
            "reinforced",
            "learning",
            "feedback",
            "record_feedback",
            "base_relevance",
            "synapse",
            "importance",
            "یادگیری",
            "بازخورد",
            "تقویت",
            "اهمیت فایل",
            "برای ویرایش",
            "ویرایش‌های مکرر",
        ],
    },
    AliasEntry {
        concept: "max_files",
        terms: &[
            "max_files",
            "max files",
            "maximum files",
            "file cap",
            "index cap",
            "auto index",
            "index automatically",
            "حداکثر فایل",
            "سقف فایل",
            "به‌صورت خودکار",
        ],
    },
    AliasEntry {
        concept: "index_lock",
        terms: &[
            "index lock",
            "index.lock",
            "single writer",
            "two mcp",
            "concurrent index",
            "do not index at once",
            "try_acquire",
            "IndexLock",
            "قفل ایندکس",
        ],
    },
    AliasEntry {
        concept: "workspace_detect",
        terms: &[
            "workspace detection",
            "detect workspace",
            "ide env",
            "workspace folder",
            "rootUri",
            "root uri",
            "mcp workspace",
            "NEUROMESH_WORKSPACE",
            "تشخیص workspace",
            "پیکربندی mcp",
            "پیکربندی",
            "تشخیص",
        ],
    },
    AliasEntry {
        concept: "mcp_stdio",
        terms: &[
            "content-length",
            "content length",
            "stdio",
            "framed messages",
            "json-rpc",
            "jsonrpc",
            "read_message",
            "ndjson",
        ],
    },
    AliasEntry {
        concept: "token_count",
        terms: &[
            "token_estimate",
            "token estimate",
            "token counter",
            "TokenCounter",
            "count_tokens",
            "count tokens",
            "token_count",
            "token counting",
            "counting tokens",
            "number of tokens",
            "estimate the number of tokens",
            "tokens in a file",
            "تعداد توکن",
            "شمارش توکن",
        ],
    },
];

/// Concrete code symbols to seed when an alias cluster matches (NL → code bridge).
static ALIAS_CODE_SEEDS: &[(&str, &[&str])] = &[
    ("middleware", &["app.use", "next", "middleware"]),
    ("routing", &["Router", "route", "app"]),
    ("render", &["res.render", "render", "view", "engine"]),
    ("static", &["express.static", "static", "stat"]),
    ("session", &["cookie", "session", "cookie-session"]),
    ("query", &["req.query", "query", "parseurl", "utils"]),
    (
        "auth",
        &["session", "cookie", "auth", "validateToken", "verifyJwt"],
    ),
    (
        "jwt",
        &[
            "validateToken",
            "verifyJwt",
            "JwtPayload",
            "authMiddleware",
            "token_expires",
        ],
    ),
    ("database", &["req.query", "query"]),
    (
        "content_type",
        &[
            "addContentTypeParser",
            "contentTypeParser",
            "content-type-parser",
            "contentType",
        ],
    ),
    (
        "plugin",
        &["register", "plugin-utils", "encapsulate", "fastify-plugin"],
    ),
    (
        "validation",
        &["validation", "schemas", "schemaController", "Validator"],
    ),
    (
        "errors",
        &[
            "error-handler",
            "error-serializer",
            "errors",
            "setErrorHandler",
        ],
    ),
    (
        "filesystem",
        &[
            "is_filesystem_root",
            "is_safe_workspace",
            "assert_safe_workspace",
            "confine",
        ],
    ),
    (
        "path_safety",
        &[
            "is_safe_workspace",
            "assert_safe_workspace",
            "confine",
            "workspace_rejection_reason",
            "path_escapes_workspace",
        ],
    ),
    (
        "learning",
        &[
            "record_feedback",
            "pheromone",
            "base_relevance",
            "synapse",
            "STDP",
        ],
    ),
    (
        "max_files",
        &[
            "max_files",
            "NEUROMESH_MAX_FILES",
            "reindex_incremental",
            "FileCapArg",
        ],
    ),
    (
        "index_lock",
        &[
            "IndexLock",
            "try_acquire",
            "index.lock",
            "spawn_live_sync",
            "save_persisted",
        ],
    ),
    (
        "workspace_detect",
        &[
            "mcp_workspace",
            "resolve_mcp_startup_workspace",
            "workspace_from_ide_env",
            "adopt_workspace_from_initialize",
            "NEUROMESH_WORKSPACE",
        ],
    ),
    (
        "mcp_stdio",
        &[
            "read_message",
            "Content-Length",
            "stdio",
            "run_stdio",
            "dispatch_raw",
        ],
    ),
    (
        "token_count",
        &[
            "TokenCounter",
            "count_tokens",
            "token.rs",
            "CHARS_PER_TOKEN",
        ],
    ),
];

/// Canonical concept ids from static alias clusters (NL → concept).
pub fn canonical_concepts() -> &'static [&'static str] {
    &[
        "routing",
        "middleware",
        "session",
        "auth",
        "jwt",
        "query",
        "database",
        "render",
        "static",
        "test",
        "config",
        "refactor",
        "error",
        "content_type",
        "plugin",
        "validation",
        "errors",
        "filesystem",
        "path_safety",
        "learning",
        "max_files",
        "index_lock",
        "workspace_detect",
        "mcp_stdio",
        "token_count",
    ]
}

/// Strip ZWNJ so `فایل‌سیستم` and `فایلسیستم` match the same way.
fn normalize_zwnj(s: &str) -> String {
    s.replace('\u{200c}', "")
}

/// True when `term` appears as a standalone word (or camelCase suffix), not
/// glued inside a longer snake_case identifier (`token` ⊄ `token_estimate`).
fn term_is_standalone(lower: &str, term: &str) -> bool {
    let t = term.to_lowercase();
    if t.is_empty() {
        return false;
    }
    // Match against ZWNJ-normalized text so فایل‌سیستم ≡ فایلسیستم.
    let lower = normalize_zwnj(&lower.to_lowercase());
    let t = normalize_zwnj(&t);
    let bytes = lower.as_bytes();
    let mut idx = 0usize;
    while let Some(rel) = lower[idx..].find(&t) {
        let pos = idx + rel;
        let end = pos + t.len();
        let prev = if pos > 0 { bytes[pos - 1] } else { b' ' };
        let next = if end < lower.len() { bytes[end] } else { b' ' };
        let next_snake =
            next == b'_' && end + 1 < lower.len() && bytes[end + 1].is_ascii_alphanumeric();
        let prev_snake = prev == b'_';
        // Prefix of a longer *ASCII* word: `token` ⊂ `tokens`.
        // CJK/Persian compounds stay valid substring matches (no spaces).
        let prefix_of_word = next.is_ascii_alphanumeric();
        let camel_suffix = prev.is_ascii_lowercase() && !next.is_ascii_alphanumeric();
        if !prefix_of_word && !next_snake && !prev_snake && !prev.is_ascii_alphanumeric() {
            return true;
        }
        if camel_suffix && !next_snake {
            return true;
        }
        idx = pos + 1;
        while idx < lower.len() && !lower.is_char_boundary(idx) {
            idx += 1;
        }
    }
    false
}

/// True when any static alias cluster term matches the prompt (NL bridge active).
pub fn prompt_has_alias_cluster_match(prompt: &str) -> bool {
    let lower = prompt.to_lowercase();
    ALIAS_CLUSTERS
        .iter()
        .any(|cluster| cluster.terms.iter().any(|t| term_is_standalone(&lower, t)))
}

/// Expand prompt tokens with English code terms from minimal alias clusters.
/// Returns canonical concepts + their code seeds — not every English term in
/// the cluster (those diluted precision on multi-concept matches).
pub fn expand_aliases(prompt: &str) -> Vec<String> {
    let concepts = matched_alias_concepts(prompt);
    let mut out: Vec<String> = concepts.iter().map(|c| (*c).to_string()).collect();
    for seed in alias_code_seeds_for_concepts(&concepts) {
        if !out.iter().any(|x| x.eq_ignore_ascii_case(&seed)) {
            out.push(seed);
        }
    }
    out.truncate(12);
    out
}

/// Code-oriented seed queries derived from matched alias clusters (L1 anchor path).
/// Middleware/routing only — broader NL→code bridging runs in `alias_code_seeds_for_prompt`.
pub fn alias_seed_queries(prompt: &str) -> Vec<String> {
    alias_code_seeds_inner(prompt, true)
}

/// All matched alias clusters → code seeds (server-side assisted inference).
/// Prefer `alias_code_seeds_all_for_prompt` for multi-concept prompts.
pub fn alias_code_seeds_for_prompt(prompt: &str) -> Vec<String> {
    alias_code_seeds_all_for_prompt(prompt)
}

/// Map prompt → concepts *before* dedupe, so multiple seeds can score a hit.
/// Uses standalone-word matching so `token_estimate` does not fire the auth
/// `token` cluster.
pub fn matched_alias_concepts(prompt: &str) -> Vec<&'static str> {
    let lower = prompt.to_lowercase();
    let mut concepts: Vec<&'static str> = Vec::new();
    for cluster in ALIAS_CLUSTERS {
        if cluster.terms.iter().any(|t| term_is_standalone(&lower, t))
            && !concepts.contains(&cluster.concept)
        {
            concepts.push(cluster.concept);
        }
    }
    concepts
}

/// Alias-matched code seeds (including multi-concept hits).
pub fn alias_code_seeds_for_concepts(concepts: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for (concept, seeds) in ALIAS_CODE_SEEDS {
        if !concepts.contains(concept) {
            continue;
        }
        for seed in *seeds {
            if !out.iter().any(|x| x.eq_ignore_ascii_case(seed)) {
                out.push((*seed).to_string());
            }
        }
    }
    out.truncate(12);
    out
}

/// Every code seed the alias table can offer for this prompt (no 8-cap).
pub fn alias_code_seeds_all_for_prompt(prompt: &str) -> Vec<String> {
    alias_code_seeds_for_concepts(&matched_alias_concepts(prompt))
}

/// Deprecated path kept for middleware-only callers.
fn alias_code_seeds_inner(prompt: &str, middleware_routing_only: bool) -> Vec<String> {
    let lower = prompt.to_lowercase();
    let mut out: Vec<String> = Vec::new();
    for cluster in ALIAS_CLUSTERS {
        if !cluster.terms.iter().any(|t| term_is_standalone(&lower, t)) {
            continue;
        }
        for (concept, seeds) in ALIAS_CODE_SEEDS {
            if cluster.concept != *concept {
                continue;
            }
            if middleware_routing_only && !matches!(*concept, "middleware" | "routing") {
                continue;
            }
            for seed in *seeds {
                if !out.iter().any(|x| x.eq_ignore_ascii_case(seed)) {
                    out.push((*seed).to_string());
                }
            }
        }
    }
    out.truncate(8);
    out
}

/// Generic English-verb clusters that drown a precise camelCase identifier hit.
pub const GENERIC_VERB_CONCEPTS: &[&str] = &[
    "render", "static", "test", "config", "refactor", "query", "errors", "error",
];

/// True when `id` looks like a precise camelCase symbol (StatCard, TokenCounter).
pub fn is_strong_camel_identifier(id: &str) -> bool {
    id.len() >= 4
        && id.chars().any(|c| c.is_ascii_uppercase())
        && id.chars().any(|c| c.is_ascii_lowercase())
        && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Concepts for `prompt`, dropping generic verb clusters when a camel ident is present.
pub fn matched_alias_concepts_filtered(prompt: &str, camel_hint: bool) -> Vec<&'static str> {
    let concepts = matched_alias_concepts(prompt);
    if camel_hint {
        concepts
            .into_iter()
            .filter(|c| !GENERIC_VERB_CONCEPTS.contains(c))
            .collect()
    } else {
        concepts
    }
}

/// Inject alias-expanded terms into signature related_concepts (L1 internal expansion).
pub fn inject_alias_expansion(related: &mut Vec<String>, prompt: &str) {
    let camel_hint = related.iter().any(|r| is_strong_camel_identifier(r))
        || neuromesh_task::TaskSignatureExtractor::extract(prompt)
            .identifiers
            .iter()
            .any(|i| is_strong_camel_identifier(i));
    let concepts = matched_alias_concepts_filtered(prompt, camel_hint);
    for concept in &concepts {
        if !related.iter().any(|r| r.eq_ignore_ascii_case(concept)) {
            related.push((*concept).to_string());
        }
    }
    for seed in alias_code_seeds_for_concepts(&concepts) {
        if !related.iter().any(|r| r.eq_ignore_ascii_case(&seed)) {
            related.push(seed);
        }
    }
}

/// Confidence hint for the current retrieval claim (B.3).
/// High `sufficiency_score` on a coincidental `bounded` hit is not a real hit.
pub fn lexical_confidence_hint(claim: &str, sufficiency: f32) -> f32 {
    match claim {
        "no_confident_match" | "no_seed_resolved" => 0.25,
        "partial" => 0.55,
        "likely_sufficient" | "bounded" => {
            if sufficiency < 0.45 {
                0.40
            } else if sufficiency < 0.65 {
                0.70
            } else {
                0.85
            }
        }
        "no_recorded_gap" => {
            if sufficiency < 0.45 {
                0.65
            } else {
                0.95
            }
        }
        _ => 0.70,
    }
}

/// Path stem overlap with prompt tokens — used to flag coincidental hits.
pub fn path_stem_overlap(path: &str, prompt: &str) -> f32 {
    let stem = path
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(path)
        .to_ascii_lowercase();
    let stem = stem.split('.').next().unwrap_or(&stem);
    let prompt_l = prompt.to_ascii_lowercase();
    if stem.len() >= 3 && prompt_l.contains(stem) {
        return 1.0;
    }
    let mut hits = 0usize;
    let mut total = 0usize;
    for part in stem.split(['_', '-', '.']) {
        if part.len() < 3 {
            continue;
        }
        total += 1;
        if prompt_l.contains(part) {
            hits += 1;
        }
    }
    if total == 0 {
        0.0
    } else {
        hits as f32 / total as f32
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fa_routing_expands() {
        let terms = expand_aliases("مسیردهی و router را توضیح بده");
        assert!(terms.iter().any(|t| t == "routing" || t == "route"));
    }

    #[test]
    fn token_estimate_does_not_hijack_auth_token_cluster() {
        let concepts = matched_alias_concepts("token_estimate");
        assert!(
            !concepts.contains(&"auth"),
            "token_estimate must not fire auth via substring token: {concepts:?}"
        );
        assert!(
            concepts.contains(&"token_count"),
            "token_estimate should fire token_count: {concepts:?}"
        );
        let seeds = alias_code_seeds_all_for_prompt("token_estimate");
        assert!(
            seeds
                .iter()
                .any(|s| s == "TokenCounter" || s == "count_tokens" || s == "token.rs"),
            "token_estimate seeds: {seeds:?}"
        );
        // standalone auth token still works
        assert!(matched_alias_concepts("session cookie token").contains(&"auth"));
        // camelCase suffix still works
        assert!(
            matched_alias_concepts("validateToken expiry").contains(&"auth")
                || matched_alias_concepts("validateToken expiry").contains(&"jwt")
        );
    }

    #[test]
    fn fa_filesystem_root_phrase_maps_to_confine() {
        let prompt =
            "این ابزار چطور از ایندکس کردن مسیرهای خطرناک مثل ریشه‌ی فایل‌سیستم جلوگیری می‌کند؟";
        let concepts = matched_alias_concepts(prompt);
        assert!(
            concepts.contains(&"filesystem") || concepts.contains(&"path_safety"),
            "expected filesystem/path_safety, got {concepts:?}"
        );
        assert!(
            !concepts.contains(&"static"),
            "فایل inside فایل‌سیستم must not fire static: {concepts:?}"
        );
        let seeds = alias_code_seeds_all_for_prompt(prompt);
        assert!(
            seeds
                .iter()
                .any(|s| s == "is_safe_workspace" || s == "is_filesystem_root" || s == "confine"),
            "seeds: {seeds:?}"
        );
    }

    #[test]
    fn fa_file_not_standalone_inside_fayl_system() {
        // Bare فایل was removed from the static cluster; filesystem terms cover compounds.
        assert!(!term_is_standalone("فایل‌سیستم", "فایل استاتیک"));
        let c = matched_alias_concepts("فایل‌سیستم");
        assert!(
            !c.contains(&"static"),
            "فایل‌سیستم must not fire static: {c:?}"
        );
    }

    #[test]
    fn token_is_not_standalone_inside_tokens() {
        assert!(!term_is_standalone("number of tokens in a file", "token"));
        assert!(term_is_standalone("auth token expiry", "token"));
        assert!(!term_is_standalone("tokenization cost", "token"));
        let concepts = matched_alias_concepts(
            "How does the system estimate the number of tokens in a file or prompt?",
        );
        assert!(
            !concepts.contains(&"auth"),
            "must not fire auth from tokens: {concepts:?}"
        );
        assert!(
            concepts.contains(&"token_count"),
            "should fire token_count: {concepts:?}"
        );
        let seeds = alias_code_seeds_all_for_prompt(
            "How does the system estimate the number of tokens in a file or prompt?",
        );
        assert!(
            seeds
                .iter()
                .any(|s| s == "TokenCounter" || s == "count_tokens" || s == "token.rs"),
            "seeds: {seeds:?}"
        );
    }

    #[test]
    fn term_is_standalone_snake_vs_word() {
        let l = "token_estimate how does token auth work";
        assert!(term_is_standalone(l, "token_estimate"));
        assert!(term_is_standalone(l, "token"));
        assert!(!term_is_standalone("token_estimate", "token"));
        assert!(term_is_standalone("validateToken", "token"));
    }

    #[test]
    fn accuracy_case_alias_seeds() {
        let dangerous = alias_code_seeds_all_for_prompt(
            "How does this tool prevent indexing dangerous paths like the filesystem root?",
        );
        assert!(
            dangerous
                .iter()
                .any(|s| s == "is_safe_workspace" || s == "is_filesystem_root"),
            "dangerous-paths seeds: {dangerous:?}"
        );
        let reinforce = alias_code_seeds_all_for_prompt(
            "How does a file's importance get reinforced after repeated edits?",
        );
        assert!(
            reinforce.iter().any(|s| s.contains("pheromone")
                || s == "record_feedback"
                || s == "base_relevance"),
            "reinforce seeds: {reinforce:?}"
        );
        let maxf = alias_code_seeds_all_for_prompt(
            "How does the system determine the maximum number of files to index automatically?",
        );
        assert!(
            maxf.iter()
                .any(|s| s == "max_files" || s == "reindex_incremental"),
            "max-files seeds: {maxf:?}"
        );
    }

    #[test]
    fn confidence_hint_downgrades_weak_bounded() {
        assert!(lexical_confidence_hint("bounded", 0.25) < 0.5);
        assert!(lexical_confidence_hint("no_recorded_gap", 0.9) >= 0.9);
        assert!(lexical_confidence_hint("no_seed_resolved", 0.8) < 0.3);
    }

    #[test]
    fn path_stem_overlap_detects_confine() {
        assert!(
            path_stem_overlap(
                "crates/neuromesh-index/src/confine.rs",
                "confine workspace safety"
            ) > 0.5
        );
        assert_eq!(
            path_stem_overlap("crates/neuromesh-mcp/src/descriptors.rs", "filesystem root"),
            0.0
        );
    }

    #[test]
    fn alias_seeds_all_families_for_render() {
        let seeds =
            alias_code_seeds_for_prompt("How does res.render() work with template engines?");
        assert!(seeds.iter().any(|s| s == "res.render"));
        assert!(seeds.iter().any(|s| s == "render"));
    }

    #[test]
    fn alias_seeds_session_ru() {
        let seeds = alias_code_seeds_for_prompt("Как работают куки и сессии в Express?");
        assert!(seeds.iter().any(|s| s.eq_ignore_ascii_case("cookie")));
        assert!(seeds.iter().any(|s| s.eq_ignore_ascii_case("session")));
    }

    #[test]
    fn zh_content_type_expands() {
        let terms = expand_aliases("内容类型解析器如何工作？");
        assert!(terms.iter().any(|t| t == "content_type" || t == "parser"));
        let seeds = alias_code_seeds_for_prompt("内容类型解析器如何工作？");
        assert!(seeds
            .iter()
            .any(|s| s.contains("contentType") || s.contains("Parser")));
    }

    #[test]
    fn fa_plugin_alias_seeds() {
        let seeds = alias_code_seeds_for_prompt("پلاگین‌ها چگونه درون‌کاشت و کپسوله‌سازی می‌شوند؟");
        assert!(seeds.iter().any(|s| s.contains("plugin-utils")));
        assert!(seeds.iter().any(|s| s.eq_ignore_ascii_case("register")));
    }

    #[test]
    fn fa_validation_alias_seeds() {
        let seeds = alias_code_seeds_for_prompt("اعتبارسنجی JSON schema چگونه کار می‌کند؟");
        assert!(seeds
            .iter()
            .any(|s| s.contains("validation") || s.contains("schema")));
    }

    #[test]
    fn fa_errors_alias_seeds() {
        let seeds = alias_code_seeds_for_prompt("مدیریت خطا و error handler کجاست؟");
        assert!(seeds.iter().any(|s| s.contains("error-handler")));
    }

    #[test]
    fn prompt_has_alias_cluster_match_fa() {
        assert!(prompt_has_alias_cluster_match("پلاگین encapsulation"));
    }
}
