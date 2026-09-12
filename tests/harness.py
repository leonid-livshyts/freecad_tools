# -*- coding: utf-8 -*-
"""Tiny assertion harness for FreeCAD tests.

freecadcmd exits 0 even when a script raises, so a caller cannot use the exit
status to tell pass from fail. Every test therefore ends by printing a
"RESULT: PASS" or "RESULT: FAIL (n)" line, which is what the run command greps
for. FreeCAD also mirrors stdout, so expect every line to appear twice.
"""

import math
import os
import sys

# Tests live in tests/, the module under test sits one level up.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Checks(object):
    """Collects pass/fail results and prints the sentinel line."""

    def __init__(self, title):
        self.title = title
        self.passed = 0
        self.failed = []
        self.log = []
        self._say("== %s ==" % title)

    def _say(self, line):
        """Print, and keep a copy for HARNESS_OUT.

        The GUI binary swallows stdout into FreeCAD's Report view, so a test
        that has to run under the GUI (the dialog) needs its results written to
        a file to be readable from outside.
        """
        self.log.append(line)
        print(line)

    def ok(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            self._say("  ok   %s" % name)
        else:
            self.failed.append(name)
            self._say("  FAIL %s %s" % (name, detail))

    def close(self, name, got, want, tol=1e-6):
        """Assert a float is within tol of the wanted value."""
        self.ok(name, abs(got - want) <= tol,
                "got %.6f want %.6f (tol %g)" % (got, want, tol))

    def between(self, name, got, low, high):
        self.ok(name, low <= got <= high,
                "got %.6f, wanted between %.6f and %.6f" % (got, low, high))

    def report(self):
        self._say("%s: %d passed, %d failed"
                  % (self.title, self.passed, len(self.failed)))
        if self.failed:
            self._say("RESULT: FAIL (%d) -> %s"
                      % (len(self.failed), ", ".join(self.failed)))
        else:
            self._say("RESULT: PASS")
        out = os.environ.get("HARNESS_OUT")
        if out:
            with open(out, "w") as handle:
                handle.write("\n".join(self.log) + "\n")


def max_radius(shape):
    """Largest vertex distance from the Z axis.

    Use this instead of BoundBox on anything swept: the bound box of a swept
    BSpline comes from its control poles and overshoots the real surface badly.
    """
    return max(math.hypot(v.Point.x, v.Point.y) for v in shape.Vertexes)


def min_radius(shape):
    return min(math.hypot(v.Point.x, v.Point.y) for v in shape.Vertexes)


def z_extent(shape):
    """(lowest, highest) vertex z.

    Same reason as max_radius: BoundBox on a shape carrying swept thread faces
    reports the control-pole hull, which overshoots a trimmed shank by a whole
    pitch at each end even though the geometry is correctly flat-ended.
    """
    zs = [v.Point.z for v in shape.Vertexes]
    return min(zs), max(zs)
