# -*- coding: utf-8 -*-
"""Regenerate the sample document.

Run it with the headless binary from the project root:

    flatpak run --command=freecadcmd org.freecad.FreeCAD tools/make_samples.py

The output path is fixed at samples/ and is not configurable: samples belong in
samples/, never loose in the project root where they sit next to the source and
get committed by accident.
"""

import os
import sys

# Run from anywhere: resolve the project root from this file's location.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(PROJECT_ROOT, "samples")
SCREW_OUTPUT = os.path.join(SAMPLES_DIR, "screw_samples.FCStd")
NUT_OUTPUT = os.path.join(SAMPLES_DIR, "nut_samples.FCStd")

sys.path.insert(0, PROJECT_ROOT)

import FreeCAD as App
import screw
import nut

# One of every head shape, each with a drive that suits it, in a row.
HEADS = [
    ("flat", "slot"),
    ("oval", "phillips"),
    ("pan", "phillips"),
    ("round", "slot"),
    ("mushroom", "hex_socket"),
    ("truss", "slot"),
    ("hex", "none"),
]
HEAD_SPACING = 22.0

# A second row showing the thread itself across a wide range of sizes.
SIZES = [(3.0, 16.0, 0.5), (8.0, 25.0, 1.25), (20.0, 50.0, 2.5)]
SIZE_SPACING = 45.0
SIZE_ROW_Y = -60.0

# Nut samples: one of every body style, plus a screw sitting in a hex nut so
# the fit is visible rather than merely asserted.
NUT_SPACING = 26.0


def main_screws():
    if not os.path.isdir(SAMPLES_DIR):
        os.makedirs(SAMPLES_DIR)

    doc = App.newDocument("ScrewSamples")

    for index, (head, drive) in enumerate(HEADS):
        part = screw.build_screw(
            dict(screw.DEFAULTS, diameter=8.0, length=25.0, pitch=1.25,
                 head=head, drive=drive, new_document=False), doc=doc)
        part.Placement.Base = App.Vector(index * HEAD_SPACING, 0.0, 0.0)
        report(part, "%s + %s" % (head, drive))

    for index, (diameter, length, pitch) in enumerate(SIZES):
        part = screw.build_screw(
            dict(screw.DEFAULTS, diameter=diameter, length=length, pitch=pitch,
                 head="hex", drive="none", new_document=False), doc=doc)
        part.Placement.Base = App.Vector(index * SIZE_SPACING, SIZE_ROW_Y, 0.0)
        report(part, "M%g x %g x %g" % (diameter, pitch, length))

    doc.recompute()
    doc.saveAs(SCREW_OUTPUT)
    App.Console.PrintMessage("saved %s\n" % SCREW_OUTPUT)


def report(part, label):
    """Say enough about each screw to spot a broken one in the log."""
    shape = part.Group[0].Shape
    zs = [v.Point.z for v in shape.Vertexes]
    App.Console.PrintMessage(
        "%-22s solids=%d valid=%s height=%.3f volume=%.1f\n"
        % (label, len(shape.Solids), shape.isValid(),
           max(zs) - min(zs), shape.Volume))


def main_nuts():
    doc = App.newDocument("NutSamples")

    for index, (kind, label) in enumerate(nut.NUT_TYPES):
        part = nut.build_nut(
            dict(nut.DEFAULTS, diameter=8.0, pitch=1.25, kind=kind,
                 new_document=False), doc=doc)
        part.Placement.Base = App.Vector(index * NUT_SPACING, 0.0, 0.0)
        report(part, label)

    # A hex nut with a screw through it, to eyeball the fit. The screw is
    # dropped by whole pitches only: thread phase is anchored at z=0, and any
    # other offset would show the two intersecting.
    seated = nut.build_nut(
        dict(nut.DEFAULTS, diameter=8.0, pitch=1.25, kind="hex",
             new_document=False), doc=doc)
    seated.Placement.Base = App.Vector(0.0, -40.0, 0.0)
    bolt = screw.build_screw(
        dict(screw.DEFAULTS, diameter=8.0, length=25.0, pitch=1.25,
             head="hex", drive="none", new_document=False), doc=doc)
    bolt.Placement.Base = App.Vector(0.0, -40.0, -2 * 1.25)
    report(bolt, "M8 screw seated in a hex nut")

    doc.recompute()
    doc.saveAs(NUT_OUTPUT)
    App.Console.PrintMessage("saved %s\n" % NUT_OUTPUT)


main_screws()
main_nuts()
