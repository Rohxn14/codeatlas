; CodeAtlas addition: upstream C++ tags.scm tags definitions only, no calls.
(call_expression
    function: (identifier) @name) @reference.call

(call_expression
    function: (field_expression
        field: (field_identifier) @name)) @reference.call

; `ns::f()` and `C::make()`: the receiver becomes `ns` / `C`.
(call_expression
    function: (qualified_identifier
        name: (identifier) @name)) @reference.call

; `a::B::f()` and `a::b::C::f()`: queries cannot recurse, so two more levels.
(call_expression
    function: (qualified_identifier
        name: (qualified_identifier
            name: (identifier) @name))) @reference.call

(call_expression
    function: (qualified_identifier
        name: (qualified_identifier
            name: (qualified_identifier
                name: (identifier) @name)))) @reference.call

; `f<T>()`, `ns::f<T>()`
(call_expression
    function: (template_function
        name: (identifier) @name)) @reference.call

(call_expression
    function: (qualified_identifier
        name: (template_function
            name: (identifier) @name))) @reference.call

; Namespaces are scopes, as Rust's `mod` is: `namespace ns { int f(); }` gives `ns.f`.
(namespace_definition
    name: (namespace_identifier) @name) @definition.module
