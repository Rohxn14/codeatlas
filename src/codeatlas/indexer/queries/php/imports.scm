; PHP imports. `use App\Models\User;` and `use App\Models\User as U;` are one clause with
; the full name as target. A grouped `use App\{A, B as C};` has one @import per clause:
; target `App`, name `A` (the profile joins them with a backslash), alias for `as`.
; `require`/`include` (and `_once`) with a literal path are file imports; for
; `__DIR__ . '/x.php'` the target is `/x.php`, relative to the including file.
; The `namespace` declaration is the file's `package`.
(namespace_definition name: (namespace_name) @package.name)

(namespace_use_declaration
    (namespace_use_clause
        .
        [(qualified_name) (name)] @import.target
        alias: (name)? @import.alias) @import)

(namespace_use_declaration
    (namespace_name) @import.target
    body: (namespace_use_group
        (namespace_use_clause
            .
            [(qualified_name) (name)] @import.name
            alias: (name)? @import.alias) @import))

(require_expression (_ (string_content) @import.target)) @import

(require_once_expression (_ (string_content) @import.target)) @import

(include_expression (_ (string_content) @import.target)) @import

(include_once_expression (_ (string_content) @import.target)) @import

(require_expression (binary_expression right: (string (string_content) @import.target))) @import

(require_once_expression (binary_expression right: (string (string_content) @import.target))) @import

(include_expression (binary_expression right: (string (string_content) @import.target))) @import

(include_once_expression (binary_expression right: (string (string_content) @import.target))) @import
