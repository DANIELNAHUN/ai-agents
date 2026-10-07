# DOCX and PDF generation

Document generation is an opt-in stage after a persisted application record has
been analyzed. It uses `CV_TEMPLATE_PATH` (defaulting to the local
`files/templates/Template CV.docx`) and writes generated files under
`CV_OUTPUT_DIR`.

The real output template currently contains six required markers, each exactly
once:

- `{{resume_experience_fractalia}}`
- `{{list_bullet_goals_objetives_work_fractalia}}`
- `{{tools_list_fractalia}}`
- `{{resume_experience_cableclub}}`
- `{{list_bullet_goals_objetives_work_cableclub}}`
- `{{tools_list_cableclub}}`

Rendering changes marker content only, preserves the source template, and
refuses to overwrite an existing output unless explicitly requested. Missing,
duplicated, or unknown markers fail with `TemplateRenderError`.

PDF conversion runs the external command:

```text
soffice --headless --convert-to pdf --outdir <output-directory> <input.docx>
```

Microsoft Word is not required. Install LibreOffice and put `soffice` on PATH,
or configure an absolute command path. If it is unavailable, conversion raises
`PDFConversionError` with remediation. DOCX readability and PDF page count/text
extraction are validated structurally, but a final visual review is still
required for every generated CV and template.
