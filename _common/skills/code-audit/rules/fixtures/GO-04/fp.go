package main

import "sync"

var mu sync.Mutex
var m = map[string]int{}

func f() {
	go func() { mu.Lock(); m["a"] = 1; mu.Unlock() }()
}
