# survey-any-tools

Tooling for the **survey-any** personal research knowledge base: the `survey-any`
CLI, Claude Code skills/agents, document templates, and controlled-vocabulary schema.

Content (topics, references, courses, personal notes) lives in a **separate**
repository. This repo is content-agnostic and public; it operates on whatever
content root you point it at.

## What's here

| Path | Role |
|------|------|
| `survey_any/` | The `survey-any` CLI (Python, stdlib-only). 20 subcommands: `doctor`, `new`, `backlinks`, `build-index`, `search-fulltext`, `recall`, `review-due`, `trace`, `suggest-related`, ... |
| `.apm/skills/`, `.claude/skills/`, `.claude/agents/` | Claude Code skills (`survey`, `ask`, `survey-paper`, ...) and agents |
| `templates/` | Frontmatter templates for new topics/references/courses/lessons |
| `vocab/*-levels.yml` | Fixed enum schema (relation types, evidence strength, maturity). Rationale docs; the runtime source of truth is `survey_any/_schema.py` |
| `mise.toml` | Task wrappers over the CLI plus composite recipes |
| `docs/adr/` | Architecture decision records |

## Install

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/bigdra50/survey-any-tools
survey-any --help
```

Or run without installing:

```bash
uvx --from git+https://github.com/bigdra50/survey-any-tools survey-any --help
```

## Content root resolution

Every command operates on a **content root** (the directory holding `topics/`,
`references/`, ...). It is resolved in this order:

1. `SURVEY_ANY_ROOT` environment variable
2. the current working directory, searched upward for a `topics/` marker

```bash
# from inside a content repo
cd ~/path/to/your-content && survey-any doctor

# or point at it explicitly
SURVEY_ANY_ROOT=~/path/to/your-content survey-any doctor
```

The CLI is offline-first: it reads the local content root and needs no network.

## Skills

Skills are distributed via [apm](https://github.com/microsoft/apm). They locate a
content repo and drive the CLI (directly, or through the content repo's thin
`mise` task layer).

## License

MIT
