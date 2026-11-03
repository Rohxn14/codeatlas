; CodeAtlas addition: upstream tags.scm labels C# calls `@reference.send`, which the
; adapter does not read, so C# had no calls at all. Tag both call shapes as calls.
(invocation_expression
    function: (identifier) @name) @reference.call

(invocation_expression
    function: (member_access_expression
        name: (identifier) @name)) @reference.call
