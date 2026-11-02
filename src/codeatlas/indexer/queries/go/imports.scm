; Go imports: single and grouped. @import.alias is the name written before the path:
; an identifier, `.` (dot import) or `_` (blank import).
(package_clause (package_identifier) @package.name)

(import_spec
  name: [(package_identifier) (dot) (blank_identifier)]? @import.alias
  path: (interpreted_string_literal (interpreted_string_literal_content) @import.target)) @import

(import_spec
  name: [(package_identifier) (dot) (blank_identifier)]? @import.alias
  path: (raw_string_literal (raw_string_literal_content) @import.target)) @import
