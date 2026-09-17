package main

import "context"

func main(ctx context.Context) {
	c := make(chan int, 10)
	go func() {
		defer close(c)
		defer func() { _ = recover() }()   // 不让 panic 掀翻整个进程
		for {
			select {
			case c <- 1:
			case <-ctx.Done():
				return
			}
		}
	}()
}
