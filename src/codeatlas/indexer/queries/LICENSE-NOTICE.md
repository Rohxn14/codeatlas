# Query sources and licences

CodeAtlas reads each grammar's `queries/tags.scm` from the installed grammar package where the package ships one (Python, JavaScript, TypeScript, Go, Java, Rust, PHP, C, C++, Ruby). Those files are not copied here; they come with the packages under each package's own licence (all MIT).

## Vendored

| File | Source | Licence |
| --- | --- | --- |
| `c_sharp/tags.scm` | [tree-sitter/tree-sitter-c-sharp](https://github.com/tree-sitter/tree-sitter-c-sharp), `queries/tags.scm` at `master` (identical to tag `v0.23.1`); the `tree-sitter-c-sharp` pip package does not include it | MIT. Copyright (c) 2014-2023 Max Brunsfeld, Damien Guard, Amaan Qureshi, and contributors |

The vendored file is unchanged.

## Written for CodeAtlas

`c/extra.scm`, `cpp/extra.scm`, `c_sharp/extra.scm` and `rust/extra.scm` add call captures the upstream queries lack. They are part of CodeAtlas and appended after the upstream query for that language.
