// SAFETY: 调用方保证 p 已对齐且可读，长度至少 1 字节
pub unsafe fn read_at(p: *const u8) -> u8 {
    *p
}
