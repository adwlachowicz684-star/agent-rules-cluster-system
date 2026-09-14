package main

import "sync"

var wg sync.WaitGroup

func f() {
	wg.Add(1)
	go func() { defer wg.Done(); work() }()
	wg.Wait()
}
