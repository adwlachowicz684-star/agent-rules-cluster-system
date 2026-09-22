class A {
  void f() {
    try { Thread.sleep(100); }
    catch (InterruptedException e) { log.warn("x"); }
  }
}
