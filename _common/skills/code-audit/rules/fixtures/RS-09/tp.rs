pub fn as_bytes(v: &u32) -> &[u8] {
    unsafe { std::slice::from_raw_parts(v as *const u8, 4) }
}
