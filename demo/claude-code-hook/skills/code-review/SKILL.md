---
name: code-review
description: Code review assistance with style checking and best practices
allowed-tools:
  - WriteCode
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: your-name
  tags: ["python", "code-quality"]
---

# Code Review Skill

Use this skill when reviewing code for quality, style, and best practices.

## When to Use

- User asks for code review or feedback
- User wants to improve code quality
- User needs help with refactoring

## Process

## Process

1. **Analyze Structure**: Review overall code organization
2. **Check Style**: Reference the style guide in references and run the check_style script to verify compliance
3. **Identify Issues**: Find bugs, security issues, performance problems
4. **Suggest Improvements**: Provide actionable recommendations

## scripts Scripts:
  - name: check_style
    path: scripts/check_style.py
    description: Analyzes code for style violations

## References:
  - name: Style Guide
    path: references/style-guide.md
    description: Coding style guidelines for code review

## Best Practices

- Focus on the most impactful issues first
- Explain the "why" behind suggestions
- Provide code examples for fixes