package main

import "sync"

var wg sync.WaitGroup

func f() {
	wg.Add(1)
	go work()
	wg.Wait()
}
