package main

import "context"

func f(ctx context.Context) {
	go func() {
		defer func() { _ = recover() }()   // panic 不掀翻进程
		select {
		case <-ctx.Done():   // 有退出机制
			return
		}
	}()
}
