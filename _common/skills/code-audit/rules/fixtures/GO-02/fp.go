package main

import (
	"context"
	"net/http"
)

func f(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()   // 不关会泄漏连接
	return io.ReadAll(resp.Body)
}
