# Quotations project — agent instructions

## Required skill: docx

This project generates Word proposals (`.docx`). Always load the project skill
`docx` (`.claude/skills/docx/SKILL.md`) before reading, generating, or reviewing
any `.docx` file or any code in `src/quotation_agents/documents.py`.

If the skill is missing, install it at project level (the SessionStart hook in
`.claude/settings.json` does this automatically):

```bash
npx skills add https://github.com/anthropics/skills --skill docx -a claude-code -y
```

The pinned version lives in `skills-lock.json`.

## Commercial proposal design

The commercial output (`generate_commercial_proposal_documents`) follows the
approved client template: Arial, US Letter, centered bold title
"Propuesta Comercial — <project>", bold metadata labels, numbered 14pt
section headings, a bordered 3-column estimation table with a bold TOTAL row,
bullet lists for inclusions/exclusions, and a footer with the page number and
"<client> - <project>".
