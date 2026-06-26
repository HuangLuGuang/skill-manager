package main

import (
	"fmt"
	"os"

	"skill-manager/scanner/internal/config"
	"skill-manager/scanner/internal/runner"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		fmt.Fprintln(os.Stderr)
		fmt.Fprintln(os.Stderr, config.Usage())
		os.Exit(1)
	}
}

func run(args []string) error {
	cfg, err := config.Parse(args)
	if err != nil {
		return err
	}
	result, outputAbs, err := runner.Scan(cfg, runner.Options{})
	if err != nil {
		return err
	}
	fmt.Printf("scanned %d skills, submitted %d, failed %d\n", result.Found, result.Submitted, result.Failed)
	if result.Failed > 0 {
		fmt.Println("failed skills:")
		for _, item := range result.Skills {
			if item.SubmitError == "" {
				continue
			}
			name := item.Name
			if name == "" {
				name = "-"
			}
			fmt.Printf("- %s (%s): %s\n", name, item.Path, item.SubmitError)
		}
	}
	fmt.Printf("report: %s\n", outputAbs)
	return nil
}
