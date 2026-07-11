# Sanitized YouTube fixtures

These hand-authored fixtures contain no provider response, cookie, credential,
caption URL, signed query string, or media URL. They establish the deterministic
boundary at captured WebVTT bytes and structured provider observations. Live
yt-dlp canaries are deliberately outside `make check`.

`automatic-timing-blank-text.vtt` is a hand-authored structural reduction of a
private 2026-07-11 diagnostic capture. Transcript wording, video identity,
titles, names, URLs, tokens, and unrelated metadata were removed. The fixture
preserves only the `Kind`/`Language` headers, valid timing lines, the observed
single blank between timing and cue text, repeated occurrences, and minimal
rolling inline timestamp/class tags needed to exercise deterministic collapse.
