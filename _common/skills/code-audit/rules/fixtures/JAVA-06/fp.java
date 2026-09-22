class A {
  private final Object lock = new Object();
  void f() { synchronized (lock) { doWork(); } }
}
