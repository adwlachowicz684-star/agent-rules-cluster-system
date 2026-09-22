import java.util.concurrent.*;
class A {
  Map<String,String> m = new ConcurrentHashMap<>();
  void f() { new Thread(() -> m.put("a","b")).start(); }
}
