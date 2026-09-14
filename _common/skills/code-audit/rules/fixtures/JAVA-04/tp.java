import java.util.*;
class A {
  Map<String,String> m = new HashMap<>();
  void f() { new Thread(() -> m.put("a","b")).start(); }
}
