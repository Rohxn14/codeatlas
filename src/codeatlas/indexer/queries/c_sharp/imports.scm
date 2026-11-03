; C# imports. `using A.B;` brings a namespace; `using static A.B.C;` brings the members
; of class C. Both have the same shape here (the profile tells them apart by looking for
; a namespace first, then a class). `using X = A.B.C;` is an alias. The `!name` and the
; `.` anchor keep the three patterns from matching the same statement. The declared
; namespace (file-scoped or block) is the file's `package`.
(file_scoped_namespace_declaration name: [(qualified_name) (identifier)] @package.name)

(namespace_declaration name: [(qualified_name) (identifier)] @package.name)

(using_directive !name [(qualified_name) (identifier)] @import.target) @import

(using_directive
    name: (identifier) @import.alias
    .
    [(qualified_name) (identifier)] @import.target) @import
