pub fn read_n(buf: &[u8]) -> Vec<u8> {
    let content_len = u32::from_le_bytes([buf[0], buf[1], buf[2], buf[3]]) as usize;
    vec![0u8; content_len]
}
