package main

var m = map[string]int{}

func f() {
	go func() { m["a"] = 1 }()
}
