package main

import "strconv"

func f(s string) int {
	v, _ := strconv.Atoi(s)
	return v
}
