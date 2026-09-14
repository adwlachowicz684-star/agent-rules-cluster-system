package main

func f() {
	go func() {
		doRisky()
	}()
}
