# Agent Documentation Map

This directory contains internal development guidance and records for repository agents and
maintainers. Human-facing setup and operation procedures remain under [`../docs/recipes/`](../docs/recipes/).

| Folder | Purpose | Use |
|---|---|---|
| [`contracts/`](contracts/) | Architecture contracts, normative requirements, and formal acceptance criteria. | Consult before planning or implementation; do not store test logs here. |
| [`plans/`](plans/) | Implementation plans and criteria for planned or active validation. | Use to scope and sequence approved work; do not archive completed execution history here. |
| [`memory/`](memory/) | Durable development memory and completed lab, execution, and test history. | Consult relevant prior records; append completed history when the approved work requires it. |

Agent roles live in [`.github/agents/`](../.github/agents/), with shared instructions and skills in
[`.github/instructions/`](../.github/instructions/) and [`.github/skills/`](../.github/skills/).
Use the [repository README](../README.md) and human procedures in `docs/` for user-facing context.
