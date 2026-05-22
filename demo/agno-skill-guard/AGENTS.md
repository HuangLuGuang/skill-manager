# Agno Demo Guidance

You are an expert in Python, Agno framework, and AI agent development.

## Core Rules

- NEVER create agents in loops. Create once and reuse.
- Always use `output_schema` for structured responses.
- PostgreSQL in production, SQLite for dev only.
- Start with a single agent. Scale to Team or Workflow only when needed.
- Do not use emojis in examples or print lines.
- Do not use f-strings for print lines that contain no variables.

## Agno Baseline

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant",
    markdown=True,
)
```

## Tool Usage

When registering tools, wrap dangerous or local tools with a Agent Manager
runtime check before executing them.

## Performance

Wrong:

```python
for query in queries:
    agent = Agent(...)
    agent.run(query)
```

Correct:

```python
agent = Agent(...)
for query in queries:
    agent.run(query)
```

## Output Schema

```python
from pydantic import BaseModel

class Result(BaseModel):
    summary: str
    findings: list[str]
```

## Docs

- Official docs: https://docs.agno.com
