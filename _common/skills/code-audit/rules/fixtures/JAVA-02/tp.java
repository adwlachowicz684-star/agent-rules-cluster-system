import java.util.concurrent.*;
class A {
  void f() {
    ExecutorService es = Executors.newFixedThreadPool(4);
    es.submit(() -> {});
  }
}
