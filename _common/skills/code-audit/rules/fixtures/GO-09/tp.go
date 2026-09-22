package main

func f(ch chan int) {
	select {
	case v := <-ch:
		handle(v)
	}
}
