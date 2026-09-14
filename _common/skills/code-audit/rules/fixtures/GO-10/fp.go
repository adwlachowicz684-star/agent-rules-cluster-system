package main

func f() {
	go func() {
		defer func() { _ = recover() }()
		doRisky()
	}()
}
