# Template library

Reusable starting points for the documents this project maintains. Copy a
template, replace the placeholders, and check the result against the source
before publishing it.

| Template | Use it for |
|---|---|
| [changelog_template.md](changelog_template.md) | The release changelog, in Keep a Changelog format |
| [architecture_template.md](architecture_template.md) | The system architecture document |

The live documents these templates were extracted from are
[CHANGELOG.md](../../CHANGELOG.md) and
[architecture.md](../architecture.md).

## Rules for every template

1. **The source is authoritative.** A document that contradicts the code is
   wrong, and the code does not get rewritten to match a stale document.
2. **Verify before writing.** Check a claim against the source or against the
   command's own `--help` output, and make the check repeatable.
3. **British English.** The house style is British spelling, and the
   documentation tests enforce it.
4. **Link every document from one index.** A document that no index reaches
   is invisible to readers.
5. **Relative links.** Use `../` to reach the repository root from a
   subdirectory, so the links resolve both on GitHub and in a checkout.

## Related

- [Documentation index](../index.md)
- [Architecture](../architecture.md)
- [Contributing](../../CONTRIBUTING.md)
