package main

import "context"

func main(ctx context.Context) {
	go func() {
		defer func() { _ = recover() }()
		<-ctx.Done()
	}()
}
