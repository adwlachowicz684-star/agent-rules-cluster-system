package main

import (
	"context"
	"net/http"
)

func f(ctx context.Context, url string) {
	resp, _ := http.Get(url)
	_ = resp
}
