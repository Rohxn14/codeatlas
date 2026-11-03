; CodeAtlas addition: upstream tags.scm tags `foo()` only when the callee is a qualified
; name or a variable, so a plain function call in the same namespace was invisible.
(function_call_expression
    function: (name) @name) @reference.call
