package main

import "context"

func f(ctx context.Context, ch chan int) {
	select {
	case v := <-ch:
		handle(v)
	case <-ctx.Done():
		return
	}
}
