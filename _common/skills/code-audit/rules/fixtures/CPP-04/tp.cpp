int counter = 0;
void f() {
    std::thread t(work);
    t.detach();
}
