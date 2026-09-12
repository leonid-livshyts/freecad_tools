# -*- coding: utf-8 -*-
"""Dialog behaviour, driven without a visible window.

Needs the GUI binary, because the whole dialog layer sits behind App.GuiUp:

    flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD \
        tests/test_dialog.py

Never calls exec() - the widgets are poked directly, the way a user would.
"""

import os

from harness import Checks
import FreeCAD as App
import screw

c = Checks("dialog")

if not App.GuiUp:
    c.ok("needs the GUI binary (see this file's docstring)", False, "GuiUp is false")
    c.report()
    os._exit(0)

from PySide import QtWidgets

dialog = screw.ScrewDialog()

# Opens on the defaults.
p = dialog.parameters()
c.close("opens on the default diameter", p["diameter"], screw.DEFAULTS["diameter"])
c.close("opens on the default length", p["length"], screw.DEFAULTS["length"])
c.close("opens on the default pitch", p["pitch"], screw.DEFAULTS["pitch"])
c.ok("opens on the default head", p["head"] == screw.DEFAULTS["head"], p["head"])
c.ok("opens on the default drive", p["drive"] == screw.DEFAULTS["drive"], p["drive"])

ok_button = dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok)
c.ok("the accept button says Create", ok_button.text() == "Create", ok_button.text())
c.ok("Create is enabled on a sane screw", ok_button.isEnabled())

# Every head is selectable and every one produces preview text.
c.ok("combo offers all seven heads", dialog.head.count() == 7,
     "got %d" % dialog.head.count())
c.ok("combo offers all four drives", dialog.drive.count() == 4,
     "got %d" % dialog.drive.count())

heads = [k for k, _ in screw.HEAD_TYPES]
for kind in heads:
    dialog.head.setCurrentIndex(heads.index(kind))
    c.ok("selecting %s keeps a preview" % kind, len(dialog.preview.text()) > 0)
    c.ok("selecting %s round-trips" % kind, dialog.parameters()["head"] == kind,
         dialog.parameters()["head"])

# A hex head is driven by its flats, so the drive combo must lock to none.
dialog.head.setCurrentIndex(heads.index("hex"))
c.ok("hex head disables the drive combo", not dialog.drive.isEnabled())
c.ok("hex head forces no recess", dialog.parameters()["drive"] == "none",
     dialog.parameters()["drive"])
dialog.head.setCurrentIndex(heads.index("pan"))
c.ok("leaving hex re-enables the drive combo", dialog.drive.isEnabled())

# Countersunk heads must say so in the preview.
dialog.head.setCurrentIndex(heads.index("flat"))
c.ok("flat head preview mentions overall length",
     "overall" in dialog.preview.text().lower(), dialog.preview.text())
dialog.head.setCurrentIndex(heads.index("pan"))
c.ok("pan head preview mentions the shank",
     "shank" in dialog.preview.text().lower(), dialog.preview.text())

# An impossible pitch must disable Create and show the error.
dialog.spins["pitch"].setValue(9.0)
c.ok("a too-coarse pitch disables Create", not ok_button.isEnabled())
c.ok("a too-coarse pitch shows an error", "Error:" in dialog.preview.text(),
     dialog.preview.text())

# Restore Defaults must undo all of it.
dialog.restore_defaults()
p = dialog.parameters()
c.close("restore puts the pitch back", p["pitch"], screw.DEFAULTS["pitch"])
c.ok("restore puts the head back", p["head"] == screw.DEFAULTS["head"], p["head"])
c.ok("restore re-enables Create", ok_button.isEnabled())

# A long fine thread stays buildable but warns.
dialog.spins["length"].setValue(200.0)
dialog.spins["pitch"].setValue(0.5)
c.ok("a long fine thread is still buildable", ok_button.isEnabled())
c.ok("a long fine thread warns", "Warning:" in dialog.preview.text(),
     dialog.preview.text())

c.report()
# FreeCAD's GUI does not return control after running a script, so end here.
os._exit(0)
