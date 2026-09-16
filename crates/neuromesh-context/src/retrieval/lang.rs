//! Cheap script detection for multi-English fallback (no model, no deps).

/// True when `text` contains a non-Latin script block (Arabic, Cyrillic, CJK, …).
/// ASCII-only input short-circuits in O(n) with no allocation — `fast` mode cost.
pub fn has_non_latin_script(text: &str) -> bool {
    if text.is_ascii() {
        return false;
    }
    text.chars().any(|c| {
        let u = c as u32;
        matches!(
            u,
            // Cyrillic
            0x0400..=0x04FF
                // Hebrew
                | 0x0590..=0x05FF
                // Arabic
                | 0x0600..=0x06FF
                // Arabic Supplement / Presentation
                | 0x0750..=0x077F
                | 0xFB50..=0xFDFF
                | 0xFE70..=0xFEFF
                // Devanagari
                | 0x0900..=0x097F
                // Thai
                | 0x0E00..=0x0E7F
                // Hiragana / Katakana
                | 0x3040..=0x30FF
                // CJK Unified / Extension A
                | 0x3400..=0x4DBF
                | 0x4E00..=0x9FFF
                // Hangul
                | 0xAC00..=0xD7AF
                // CJK Compatibility
                | 0xF900..=0xFAFF
        )
    })
}

/// Any non-ASCII alphabetic character (Vietnamese diacritics, Spanish ñ, Thai, …).
/// Distinct from `has_non_latin_script` (script blocks only).
pub fn has_non_ascii_alphabetic(text: &str) -> bool {
    if text.is_ascii() {
        return false;
    }
    text.chars().any(|c| !c.is_ascii() && c.is_alphabetic())
}

/// Cheap English-likeness: ≥2 common English function words in the prompt.
/// Used to avoid mislabeling real English queries as "uncovered language".
fn looks_like_english(text: &str) -> bool {
    let lower = text.to_ascii_lowercase();
    const STOP: &[&str] = &[
        "the", "how", "does", "is", "are", "was", "were", "this", "that", "what", "where", "when",
        "which", "who", "why", "and", "or", "of", "to", "for", "with", "from", "into", "about",
        "system", "file", "function", "method", "class", "please", "show", "find", "explain",
        "work",
    ];
    let mut hits = 0usize;
    for w in STOP {
        // Word-ish boundary via spaces/punctuation split below is enough.
        if lower
            .split(|c: char| !c.is_ascii_alphanumeric())
            .any(|tok| tok == *w)
        {
            hits += 1;
            if hits >= 2 {
                return true;
            }
        }
    }
    false
}

/// True when the prompt has no curated **native-language** alias coverage
/// (non-ASCII term or multi-word loanword phrase) and is not plain English.
///
/// Covers non-Latin scripts (Thai, Persian, …) **and** ASCII-only languages
/// outside the curated set (Hausa, …) without a per-language allowlist.
pub fn uncovered_language_prompt(prompt: &str) -> bool {
    if crate::retrieval::has_native_language_coverage(prompt) {
        return false;
    }
    if looks_like_english(prompt) {
        return false;
    }
    // Not English and no curated coverage → honest miss.
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ascii_and_latin_are_fast_path() {
        assert!(!has_non_latin_script(
            "How does load_persisted refuse oversized graphs?"
        ));
        assert!(!has_non_latin_script(""));
        assert!(!has_non_ascii_alphabetic(
            "How does load_persisted refuse oversized graphs?"
        ));
    }

    #[test]
    fn detects_persian_chinese_cyrillic_arabic() {
        assert!(has_non_latin_script("پلاگین‌ها چگونه کار می‌کنند؟"));
        assert!(has_non_latin_script("内容类型解析器如何工作？"));
        assert!(has_non_latin_script("Как работают куки и сессии?"));
        assert!(has_non_latin_script("كيف يعمل middleware؟"));
    }

    #[test]
    fn mixed_ascii_with_identifier_still_flags_non_latin() {
        // Persian question that also embeds an ASCII identifier.
        assert!(has_non_latin_script("تابع res.render() چطور کار می‌کند؟"));
    }

    #[test]
    fn vietnamese_and_thai_are_non_ascii_letters() {
        assert!(has_non_ascii_alphabetic(
            "Hệ thống ước tính số lượng token trong tệp hoặc lời nhắc như thế nào?"
        ));
        assert!(has_non_latin_script(
            "ระบบประมาณจำนวนโทเค็นในไฟล์หรือพรอมต์อย่างไร?"
        ));
    }

    #[test]
    fn uncovered_language_when_no_alias_hits() {
        // Thai has no curated terms → uncovered.
        assert!(uncovered_language_prompt(
            "ระบบประมาณจำนวนโทเค็นในไฟล์หรือพรอมต์อย่างไร?"
        ));
        // Hausa (never in curated set, pure ASCII) → uncovered.
        assert!(uncovered_language_prompt(
            "Ta yaya tsarin ke kimanta yawan token a cikin fayil ko prompt?"
        ));
        // Persian token phrase has a curated cluster — not uncovered.
        assert!(!uncovered_language_prompt(
            "سیستم چگونه تعداد توکن‌ها را تخمین می‌زند؟"
        ));
        // Vietnamese / Swahili loanword phrases in token_count — not uncovered.
        assert!(!uncovered_language_prompt(
            "Hệ thống ước tính số lượng token trong tệp hoặc lời nhắc như thế nào?"
        ));
        assert!(!uncovered_language_prompt(
            "Mfumo unakadiriaje idadi ya token katika faili au prompt?"
        ));
        // English with stopword signal — not uncovered.
        assert!(!uncovered_language_prompt(
            "How does the system estimate the number of tokens in a file or prompt?"
        ));
    }
}
