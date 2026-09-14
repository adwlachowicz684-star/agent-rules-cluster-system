package main

import (
	"context"
	"net/http"
)

func f(ctx context.Context, url string) {
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	resp, _ := http.DefaultClient.Do(req)
	_ = resp
}
