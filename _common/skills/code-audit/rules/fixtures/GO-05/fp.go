package main

import "sync"

func f(l *sync.Mutex) { l.Lock(); defer l.Unlock() }
