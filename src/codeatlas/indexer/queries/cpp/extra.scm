; CodeAtlas additions: the tags query shipped with tree-sitter-cpp has no call captures.

(call_expression
  function: [
    (identifier) @name
    (field_expression field: (field_identifier) @name)
    (field_expression field: (template_method name: (field_identifier) @name))
    (qualified_identifier name: (identifier) @name)
    (template_function name: (identifier) @name)
  ]) @reference.call
