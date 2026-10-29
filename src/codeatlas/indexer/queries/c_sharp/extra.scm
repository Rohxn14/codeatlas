; CodeAtlas additions: the upstream C# tags query captures member calls (`obj.Save()`) as
; @reference.send but has no capture for plain calls (`Save()`, `Save<T>()`).

(invocation_expression
  function: [
    (identifier) @name
    (generic_name (identifier) @name)
  ]) @reference.call
