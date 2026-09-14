package main

import "os"

func f(files []string) {
	for _, f := range files {
		func() {
			fh, _ := os.Open(f)
			defer fh.Close()
		}()
	}
}
