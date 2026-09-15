pub fn as_bytes(v: &u32) -> [u8; 4] {
    v.to_le_bytes()
}
