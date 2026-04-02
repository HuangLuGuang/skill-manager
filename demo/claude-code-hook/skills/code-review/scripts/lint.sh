#!/bin/bash
# Run linting on provided file

if [ -z "$1" ]; then
    echo "Usage: lint.sh <file>"
    exit 1
fi

ruff check "$1" 2>&1