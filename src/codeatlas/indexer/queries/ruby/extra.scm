; CodeAtlas addition: a bare word such as `validate` is an identifier, not a call node, and
; upstream tags it only with a "not a local variable" test that the adapter cannot run.
; A bare word followed by another statement has its value thrown away, so it can only be
; a method call (a local variable read there would do nothing). The last statement of a
; body may be a variable read, so it is left out: fewer calls, none invented.
(body_statement
    (identifier) @name @reference.call
    .
    (_))
