package main

import "os"

func f(files []string) error {
	for _, name := range files {
		if err := func() error {
			fh, err := os.Open(name)
			if err != nil {
				return err
			}
			defer fh.Close()
			return nil
		}(); err != nil {
			return err
		}
	}
	return nil
}
