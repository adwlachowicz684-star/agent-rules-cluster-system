pub fn count(entries: &[Entry]) -> usize {
    entries.iter().map(|e| e.size()).sum::<Option<usize>>().unwrap_or_default()
}
