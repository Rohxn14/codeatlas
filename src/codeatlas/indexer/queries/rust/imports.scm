; Rust imports. One @import per statement; a `{...}` list keeps its items as
; @import.name texts (`Y`, `z::W as V`, `q::{R, S}`) and the Rust profile expands them.
; `mod x;` (no body) is reported with alias `mod`: it brings in the child module x.
(use_declaration
  argument: [(scoped_identifier) (identifier) (crate) (self) (super)] @import.target) @import

(use_declaration
  argument: (use_as_clause path: (_) @import.target alias: (identifier) @import.alias)) @import

(use_declaration
  argument: (use_wildcard (_) @import.target "*" @import.wildcard)) @import

(use_declaration
  argument: (scoped_use_list
    path: (_) @import.target
    list: (use_list (_) @import.name))) @import

(mod_item "mod" @import.alias name: (identifier) @import.target !body) @import

(extern_crate_declaration name: (identifier) @import.target) @import
