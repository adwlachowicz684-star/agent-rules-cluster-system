use std::fs;

pub fn sizes(paths: &[&str]) -> Vec<u64> {
    paths.iter()
        .filter_map(|p| fs::metadata(p).ok())
        .map(|m| m.len())
        .collect()
}
