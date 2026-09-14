import java.io.*;
class A {
  void f() throws Exception {
    FileInputStream in = new FileInputStream("a");
    int b = in.read();
  }
}
