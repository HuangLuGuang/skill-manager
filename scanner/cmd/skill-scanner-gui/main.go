package main

import (
	"fmt"
	"os"

	"skill-manager/scanner/internal/gui"
)

func main() {
	if err := gui.Run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
