; C++ includes (the same as C). `#include "x.h"` targets `x.h`. `#include <x.h>` targets `<x.h>`: the
; grammar has no node inside the brackets, and the brackets are what tell the profile
; that only include folders are searched.
(preproc_include
  path: (string_literal (string_content) @import.target)) @import

(preproc_include
  path: (system_lib_string) @import.target) @import
