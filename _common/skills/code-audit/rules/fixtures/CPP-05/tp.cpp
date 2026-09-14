void f() {
    if (q.empty()) {
        cv.wait(lk);
    }
}
