package main

import "context"

func main(ctx context.Context) {
	go func() { <-ctx.Done() }()
}
