# -*- coding: utf-8 -*-
"""The dialog's derived-value preview text."""

from harness import Checks
import screw

c = Checks("preview")

p = dict(screw.DEFAULTS)
p.update({"diameter": 8.0, "length": 30.0, "pitch": 1.25,
          "head": "pan", "drive": "none"})
lines = screw.preview_lines(p)
text = "\n".join(lines)

c.ok("returns lines", isinstance(lines, list) and len(lines) > 0)
c.ok("names the thread", "M8" in text, text)
c.ok("reports the overall height", "34.8" in text, text)
c.ok("reports the head width", "14.4" in text, text)
c.ok("reports the turn count", "26" in text, text)
c.ok("no error on a sane screw", "Error:" not in text, text)
c.ok("no warning on a sane screw", "Warning:" not in text, text)

# Errors and warnings must surface in the preview, prefixed so the dialog can
# show them verbatim.
bad = dict(p)
bad["pitch"] = 9.0
c.ok("errors appear", "Error:" in "\n".join(screw.preview_lines(bad)),
     str(screw.preview_lines(bad)))

warn = dict(p)
warn.update({"diameter": 6.0, "length": 200.0, "pitch": 0.5})
c.ok("warnings appear", "Warning:" in "\n".join(screw.preview_lines(warn)),
     str(screw.preview_lines(warn)))

# A countersunk head reports its overall length, not shank plus head.
cs = dict(p)
cs["head"] = "flat"
cs_text = "\n".join(screw.preview_lines(cs))
c.ok("countersunk preview reports 30 overall", "30" in cs_text, cs_text)
c.ok("countersunk preview says so",
     "overall" in cs_text.lower() or "countersunk" in cs_text.lower(), cs_text)

# Every head and drive combination must produce preview text without raising.
for kind, _ in screw.HEAD_TYPES:
    for drive, _ in screw.DRIVE_TYPES:
        combo = dict(p)
        combo.update({"head": kind, "drive": drive})
        try:
            got = screw.preview_lines(combo)
            c.ok("preview for %s + %s" % (kind, drive), len(got) > 0)
        except Exception as exc:
            c.ok("preview for %s + %s" % (kind, drive), False, str(exc))

c.report()
