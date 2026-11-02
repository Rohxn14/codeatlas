; Java imports. A static import is an ordinary import of a longer name
; (`import static a.b.C.m` targets `a.b.C.m`); the Java profile tries `a/b/C/m.java`,
; then `a/b/C.java` with member `m`. A trailing `*` is reported as @import.wildcard.
(package_declaration [(scoped_identifier) (identifier)] @package.name)

(import_declaration (scoped_identifier) @import.target .) @import

(import_declaration (scoped_identifier) @import.target (asterisk) @import.wildcard) @import
