; CodeAtlas additions: the tags query shipped with tree-sitter-c has no call captures.

(call_expression
  function: [
    (identifier) @name
    (field_expression field: (field_identifier) @name)
  ]) @reference.call
