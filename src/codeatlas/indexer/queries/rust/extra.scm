; CodeAtlas additions: the tags query shipped with tree-sitter-rust misses path calls
; (`Circle::new()`, `std::mem::take()`) and turbofish calls (`parse::<u32>()`).

(call_expression
  function: [
    (scoped_identifier name: (identifier) @name)
    (generic_function function: (identifier) @name)
    (generic_function function: (scoped_identifier name: (identifier) @name))
    (generic_function function: (field_expression field: (field_identifier) @name))
  ]) @reference.call
