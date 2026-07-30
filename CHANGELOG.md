# Changelog

## 0.1.1

- Fix: Ingress path handling. The form, redirects, and "recent runs" links
  used root-relative URLs, so submitting a ticker under real Ingress went
  straight past the add-on instead of back into it (blank page, nothing in
  the log). Found on the first real install.
- Fix: dashboard page overflowed the viewport on phones (a 460px column
  floor on the section grid, plus several inline fixed-column layouts that
  couldn't respond to screen width). Added mobile breakpoints.
- Docs updated for a public repo (no Personal Access Token needed).

## 0.1.0

- Initial Home Assistant add-on release: web UI (ticker + dry-run toggle),
  Ingress panel, dashboard output, AI recommendation section for full runs.
