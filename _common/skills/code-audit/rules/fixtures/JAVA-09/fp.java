class A {
  void f() { try { g(); } catch (Exception e) { throw new RuntimeException(e); } }
}
