pub fn count(entries: &[Entry]) -> Result<usize, String> {
    entries.iter().map(|e| e.size()).sum::<Option<usize>>().ok_or_else(|| "bad size".into())
}
