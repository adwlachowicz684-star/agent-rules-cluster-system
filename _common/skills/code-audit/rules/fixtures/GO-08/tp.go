package main

import "os"

func f(files []string) {
	for _, f := range files {
		fh, _ := os.Open(f)
		defer fh.Close()
	}
}
