---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
---
# M2-B5 FTP proxy credential repair

The live credential-default-deny assertion now covers Docker's FTP proxy
variables (`FTP_PROXY` and `ftp_proxy`) in addition to HTTP, HTTPS, ALL, and
NO proxy spellings. The production container launch explicitly blanks all of
these names, preventing credentials from Docker's proxy configuration from
reaching candidate code. No pytest node was added; this is a coverage repair
of the existing real-backend conformance test.
