void f() {
    while (q.empty()) {
        cv.wait(lk);
    }
}
