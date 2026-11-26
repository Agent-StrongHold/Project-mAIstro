---
inventory-delta:
  tests/: +4
---
# 1532-p2-fence-blockquote-tests

Adds four regression tests locking the checker's fenced-code, indented-code,
blockquote and nested-list handling (P2 findings 4301014681, 4301014687):
- fenced code block status line is not flagged
- indented (four-space) code block status line is not flagged
- blockquoted status line is still flagged
- nested-list status line is still flagged
