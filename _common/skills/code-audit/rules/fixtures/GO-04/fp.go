package main

import "sync"

var mu sync.Mutex
var m = map[string]int{}

func f() {
	go func() {
		defer func() { _ = recover() }()
		mu.Lock()
		defer mu.Unlock()
		m["a"] = 1
	}()
}
