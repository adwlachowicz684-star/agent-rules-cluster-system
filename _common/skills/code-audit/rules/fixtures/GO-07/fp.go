package main

import (
	"context"
	"time"
)

func f(ctx context.Context) {
	go func() {
		defer func() { _ = recover() }()   // panic 不掀翻进程
		t := time.NewTicker(time.Second)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				poll()
			case <-ctx.Done():   // 有退出机制
				return
			}
		}
	}()
}
