import java.util.concurrent.*;
class A {
  ExecutorService es = Executors.newFixedThreadPool(4);
  void close() { es.shutdown(); }
}
