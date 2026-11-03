; Ruby imports are ordinary method calls. `require "x"`, `require_relative "x"` and
; `load "x"` with a literal argument become imports. The method name is captured as
; @import.name so the profile can tell a path relative to the file (`require_relative`)
; from a load-path name (`require`). This is the one language where @import.name is not
; an imported name.
(call
    !receiver
    method: (identifier) @import.name
    arguments: (argument_list . (string (string_content) @import.target))
    (#match? @import.name "^(require|require_relative|load)$")) @import
