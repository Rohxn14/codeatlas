"""Unified diffs become changes with new-file line ranges."""

from codeatlas.impact import Change, parse_diff

DIFF = """diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -10,3 +10,4 @@ def f():
@@ -40 +41 @@ def g():
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,5 +0,0 @@
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,5 @@
"""


def test_ranges_use_the_new_file_numbering():
    changes = parse_diff(DIFF)
    assert changes[0] == Change("src/a.py", ((10, 13), (41, 41)))


def test_added_and_deleted_files_have_no_ranges():
    changes = parse_diff(DIFF)
    assert changes[1] == Change("old.py")
    assert changes[2] == Change("new.py")


def test_empty_diff_gives_nothing():
    assert parse_diff("") == []


def test_a_pure_rename_reports_the_new_and_the_old_path():
    diff = ("diff --git a/x.py b/y.py\nsimilarity index 100%\n"
            "rename from x.py\nrename to y.py\n")
    assert parse_diff(diff) == [Change("y.py"), Change("x.py")]


def test_a_rename_with_edits_keeps_its_ranges():
    diff = ("diff --git a/x.py b/y.py\nsimilarity index 90%\nrename from x.py\n"
            "rename to y.py\n--- a/x.py\n+++ b/y.py\n@@ -2 +2 @@\n-a\n+b\n")
    assert parse_diff(diff) == [Change("y.py", ((2, 2),)), Change("x.py")]


def test_binary_and_mode_only_changes_are_whole_files():
    diff = ("diff --git a/img.png b/img.png\nindex 1..2 100644\n"
            "Binary files a/img.png and b/img.png differ\n"
            "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n")
    assert parse_diff(diff) == [Change("img.png"), Change("run.sh")]


def test_a_deleted_binary_file_without_headers_keeps_its_path():
    diff = ("diff --git a/logo.png b/logo.png\ndeleted file mode 100644\n"
            "Binary files a/logo.png and /dev/null differ\n")
    assert parse_diff(diff) == [Change("logo.png")]


def test_hunk_lines_that_look_like_headers_stay_in_the_hunk():
    diff = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
            "@@ -1,2 +1,2 @@\n select 1;\n--- old\n+++ new\n")
    assert parse_diff(diff) == [Change("q.sql", ((1, 2),))]


def test_a_diff_without_git_headers_is_read_pair_by_pair():
    diff = ("--- a.sql\n+++ a.sql\n@@ -1 +1 @@\n--- x\n+++ y\n"
            "--- b.py\n+++ b.py\n@@ -3,0 +4,2 @@\n+a\n+b\n")
    assert parse_diff(diff) == [Change("a.sql", ((1, 1),)), Change("b.py", ((4, 5),))]


def test_quoted_octal_escaped_paths_are_decoded():
    diff = ('diff --git "a/d\\303\\251.py" "b/d\\303\\251.py"\n'
            '--- "a/d\\303\\251.py"\n+++ "b/d\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n')
    assert parse_diff(diff) == [Change("dé.py", ((1, 1),))]


def test_unquoted_paths_with_spaces_come_from_the_git_line():
    diff = "diff --git a/my file.py b/my file.py\nold mode 100644\nnew mode 100755\n"
    assert parse_diff(diff) == [Change("my file.py")]
