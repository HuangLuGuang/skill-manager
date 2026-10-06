#!/bin/zsh
TRAPZERR() {
  local exit_code=$?
  unfunction TRAPZERR TRAPEXIT TRAPINT TRAPTERM 2>/dev/null || true
  cleanup
  exit "$exit_code"
}
TRAPEXIT() {
  local exit_code=$?
  unfunction TRAPZERR TRAPEXIT TRAPINT TRAPTERM 2>/dev/null || true
  cleanup
  exit "$exit_code"
}
TRAPINT() {
  unfunction TRAPZERR TRAPEXIT TRAPINT TRAPTERM 2>/dev/null || true
  cleanup
  exit 130
}
TRAPTERM() {
  unfunction TRAPZERR TRAPEXIT TRAPINT TRAPTERM 2>/dev/null || true
  cleanup
  exit 143
}
