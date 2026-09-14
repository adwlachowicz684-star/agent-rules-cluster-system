void f() {
    auto p = std::make_unique<char[]>(64);
    parse(p.get());
}
