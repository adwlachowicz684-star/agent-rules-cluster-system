fn copy_all(s: &Path) { if s.symlink_metadata()?.is_dir() { std::fs::copy(s, d)?; } }
