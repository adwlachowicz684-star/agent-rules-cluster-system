package main

func main() {
	c := make(chan int, 10)
	go func() { c <- 1 }()
}
