use std::fs;

pub fn sizes(paths: &[&str]) -> Vec<u64> {
    paths.iter().map(|p| fs::metadata(p).unwrap().len()).collect()
}
