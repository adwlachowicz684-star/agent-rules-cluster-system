import java.io.*;
class A {
  void f() throws Exception {
    try (FileInputStream in = new FileInputStream("a")) {
      int b = in.read();
    }
  }
}
