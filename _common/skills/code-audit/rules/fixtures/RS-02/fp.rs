pub fn to_index(v: u64) -> Option<u32> {
    u32::try_from(v).ok()
}
