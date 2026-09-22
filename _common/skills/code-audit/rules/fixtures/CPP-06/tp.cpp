class A {
public:
    ~A() { lock(); cleanup(); }
};
