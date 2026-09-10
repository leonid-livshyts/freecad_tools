# -*- coding: utf-8 -*-
"""Ball-bearing generator with a parameter dialog.

Original ball-bearing script 11.08.2016 by r-frank (BPLRFE/LearnFreeCAD on Youtube),
based on the ball bearing script by JMG
(http://linuxforanengineer.blogspot.de/2013/08/free-cad-bearing-script.html).

GUI layer added on top: run the macro and type the parameters in the dialog
instead of editing this file.

Run it as a FreeCAD macro (Macro -> Macros... -> Execute) and a dialog appears.
Without the GUI (FreeCADCmd) the module still works:

    import bearing
    bearing.build_bearing(bearing.DEFAULTS)
"""

__Title__ = "Ball bearing"
__Author__ = "r-frank, JMG"
__Version__ = "2.0.0"
__Comment__ = "Parametric ball bearing with a parameter input dialog"

# needed for inserting primitives
import Part
# needed for calculating the positions of the balls
import math
# needed for translation of torus
import FreeCAD as App
from FreeCAD import Base


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

# Same values the original script had hard-coded at the top of the file.
DEFAULTS = {
    "R1": 15.0,     # radius of shaft / inner radius of inner ring
    "R2": 25.0,     # outer radius of inner ring
    "R3": 30.0,     # inner radius of outer ring
    "R4": 40.0,     # outer radius of outer ring
    "TH": 15.0,     # thickness of bearing
    "NBall": 10,    # number of balls
    "RBall": 5.0,   # radius of ball
    "RR": 1.0,      # rounding radius for fillets
    "new_document": True,
}

# Order and labels used to build the dialog.
FIELDS = [
    ("R1", "Bore radius (R1)", "Inner radius of the inner ring, i.e. the shaft radius"),
    ("R2", "Inner ring outer radius (R2)", "Outer radius of the inner ring"),
    ("R3", "Outer ring inner radius (R3)", "Inner radius of the outer ring"),
    ("R4", "Outer radius (R4)", "Outer radius of the outer ring"),
    ("TH", "Thickness (TH)", "Height of the bearing along its axis"),
    ("RBall", "Ball radius (RBall)", "Radius of one ball and of the race groove"),
    ("RR", "Fillet radius (RR)", "Edge rounding on both rings, 0 disables the fillets"),
]


def ball_pitch_radius(p):
    """Distance from the bearing axis to the centre of a ball."""
    return ((p["R3"] - p["R2"]) / 2.0) + p["R2"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(p):
    """Check a parameter set.

    Returns (errors, warnings). Errors describe geometry that cannot be built
    at all; warnings describe geometry that builds but is not a usable bearing.
    Catching these here gives a readable message instead of an OCC exception.
    """
    errors = []
    warnings = []

    r1, r2, r3, r4 = p["R1"], p["R2"], p["R3"], p["R4"]
    th, rr, rball, nball = p["TH"], p["RR"], p["RBall"], int(p["NBall"])

    # Radii must grow outwards.
    if r1 <= 0:
        errors.append("Bore radius R1 must be greater than 0.")
    if r2 <= r1:
        errors.append("Inner ring outer radius R2 (%g) must be larger than bore radius R1 (%g)." % (r2, r1))
    if r3 <= r2:
        errors.append("Outer ring inner radius R3 (%g) must be larger than R2 (%g); "
                      "the gap between them is where the balls run." % (r3, r2))
    if r4 <= r3:
        errors.append("Outer radius R4 (%g) must be larger than R3 (%g)." % (r4, r3))
    if th <= 0:
        errors.append("Thickness TH must be greater than 0.")
    if nball < 1:
        errors.append("Number of balls must be at least 1.")
    if rball <= 0:
        errors.append("Ball radius RBall must be greater than 0.")

    if errors:
        # Later checks divide by these values, so stop here.
        return errors, warnings

    # The fillet is applied to every edge of each ring, so it eats into the
    # wall from both sides and into the height from top and bottom.
    if rr < 0:
        errors.append("Fillet radius RR cannot be negative.")
    elif rr > 0:
        if 2 * rr >= (r2 - r1):
            errors.append("Fillet radius RR (%g) is too large for the inner ring wall "
                          "(R2-R1 = %g); it must stay below %g." % (rr, r2 - r1, (r2 - r1) / 2.0))
        if 2 * rr >= (r4 - r3):
            errors.append("Fillet radius RR (%g) is too large for the outer ring wall "
                          "(R4-R3 = %g); it must stay below %g." % (rr, r4 - r3, (r4 - r3) / 2.0))
        if 2 * rr >= th:
            errors.append("Fillet radius RR (%g) is too large for the thickness TH (%g); "
                          "it must stay below %g." % (rr, th, th / 2.0))

    cball = ball_pitch_radius(p)

    # The groove torus is cut at mid height; a ball larger than half the
    # thickness would slice each ring into two loose halves.
    if rball > th / 2.0:
        errors.append("Ball radius RBall (%g) exceeds half the thickness (%g); "
                      "the race groove would cut the rings in two." % (rball, th / 2.0))
    # The groove must not break out through the bore or the outside diameter.
    if cball - rball <= r1:
        errors.append("The race groove reaches the bore: RBall (%g) is too large or the "
                      "inner ring is too thin (groove inner edge %g vs bore %g)."
                      % (rball, cball - rball, r1))
    if cball + rball >= r4:
        errors.append("The race groove breaks through the outside diameter: groove outer "
                      "edge %g vs R4 %g." % (cball + rball, r4))

    if errors:
        return errors, warnings

    # Buildable, but not a working bearing.
    gap = (r3 - r2) / 2.0
    if rball <= gap:
        warnings.append("Ball radius RBall (%g) does not span the gap between the rings "
                        "(half gap is %g), so the balls will not touch both races."
                        % (rball, gap))
    if nball > 1:
        spacing = 2 * cball * math.sin(math.pi / nball)
        if spacing < 2 * rball:
            warnings.append("%d balls of radius %g overlap each other on a pitch circle of "
                            "radius %g (centre spacing %.3f, needs %.3f). Reduce the ball "
                            "count or the ball radius." % (nball, rball, cball, spacing, 2 * rball))

    return errors, warnings


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def build_bearing(p, doc=None):
    """Build the bearing and add it to a document.

    p is a dict shaped like DEFAULTS. If doc is None a document is created or
    the active one is reused, following p["new_document"].
    Returns the created document objects.
    """
    errors, _ = validate(p)
    if errors:
        raise ValueError("Invalid bearing parameters:\n- " + "\n- ".join(errors))

    r1, r2, r3, r4 = p["R1"], p["R2"], p["R3"], p["R4"]
    th, rr, rball, nball = p["TH"], p["RR"], p["RBall"], int(p["NBall"])

    # first coordinate of center of ball
    cball = ball_pitch_radius(p)

    if doc is None:
        if p.get("new_document", True) or App.ActiveDocument is None:
            doc = App.newDocument("Bearing")
        else:
            doc = App.ActiveDocument
    App.setActiveDocument(doc.Name)

    objects = []

    # Inner Ring
    b1 = Part.makeCylinder(r1, th)
    b2 = Part.makeCylinder(r2, th)
    inner = b2.cut(b1)
    # get edges and apply fillets
    if rr > 0:
        inner = inner.makeFillet(rr, inner.Edges)
    # create groove and show shape
    t1 = Part.makeTorus(cball, rball)
    t1.translate(Base.Vector(0, 0, th / 2.0))
    objects.append(Part.show(inner.cut(t1), "InnerRing"))

    # Outer Ring
    b3 = Part.makeCylinder(r3, th)
    b4 = Part.makeCylinder(r4, th)
    outer = b4.cut(b3)
    # get edges and apply fillets
    if rr > 0:
        outer = outer.makeFillet(rr, outer.Edges)
    # create groove and show shape
    t2 = Part.makeTorus(cball, rball)
    t2.translate(Base.Vector(0, 0, th / 2.0))
    objects.append(Part.show(outer.cut(t2), "OuterRing"))

    # Balls
    for i in range(nball):
        ball = Part.makeSphere(rball)
        alpha = (i * 2 * math.pi) / nball
        ball.translate((cball * math.cos(alpha), cball * math.sin(alpha), th / 2.0))
        objects.append(Part.show(ball, "Ball"))

    # Keep the tree readable when several bearings share a document.
    group = doc.addObject("App::DocumentObjectGroup", "Bearing")
    group.Label = "Bearing %g-%g-%g" % (2 * r1, 2 * r4, th)
    for obj in objects:
        group.addObject(obj)

    # Make it pretty
    doc.recompute()
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxometric()
        Gui.SendMsgToActiveView("ViewFit")

    return objects


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

if App.GuiUp:
    import FreeCADGui as Gui
    # FreeCAD ships a PySide shim (Ext/PySide) that forwards to the PySide
    # version this build uses (PySide6 on FreeCAD 1.x), so this import works
    # unchanged across FreeCAD versions.
    from PySide import QtCore, QtWidgets

    class BearingDialog(QtWidgets.QDialog):
        """Parameter dialog for the ball bearing."""

        def __init__(self, values=None, parent=None):
            if parent is None:
                parent = Gui.getMainWindow()
            super(BearingDialog, self).__init__(parent)

            self.setWindowTitle("Ball bearing")
            self.setModal(True)

            values = dict(values or DEFAULTS)
            self.spins = {}

            form = QtWidgets.QFormLayout()
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

            for key, label, tip in FIELDS:
                spin = QtWidgets.QDoubleSpinBox()
                spin.setDecimals(3)
                spin.setRange(0.0, 100000.0)
                spin.setSingleStep(1.0)
                spin.setSuffix(" mm")
                spin.setValue(float(values[key]))
                spin.setToolTip(tip)
                spin.valueChanged.connect(self.update_preview)
                self.spins[key] = spin
                form.addRow(label + ":", spin)

            self.ball_count = QtWidgets.QSpinBox()
            self.ball_count.setRange(1, 1000)
            self.ball_count.setValue(int(values["NBall"]))
            self.ball_count.setToolTip("How many balls are placed around the race")
            self.ball_count.valueChanged.connect(self.update_preview)
            form.addRow("Number of balls (NBall):", self.ball_count)

            self.new_doc = QtWidgets.QCheckBox("Create a new document")
            self.new_doc.setChecked(bool(values.get("new_document", True)))
            self.new_doc.setToolTip("Unchecked, the bearing is added to the active document")
            form.addRow("", self.new_doc)

            # Derived values and problems, refreshed on every edit.
            self.preview = QtWidgets.QLabel()
            self.preview.setWordWrap(True)
            self.preview.setTextFormat(QtCore.Qt.PlainText)
            self.preview.setMinimumWidth(360)

            self.buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel
                | QtWidgets.QDialogButtonBox.RestoreDefaults
            )
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            self.buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
                self.restore_defaults
            )

            layout = QtWidgets.QVBoxLayout(self)
            layout.addLayout(form)
            layout.addWidget(self.preview)
            layout.addWidget(self.buttons)

            self.update_preview()

        def parameters(self):
            """Read the widgets back into a parameter dict."""
            p = {key: spin.value() for key, spin in self.spins.items()}
            p["NBall"] = self.ball_count.value()
            p["new_document"] = self.new_doc.isChecked()
            return p

        def restore_defaults(self):
            for key, spin in self.spins.items():
                spin.setValue(float(DEFAULTS[key]))
            self.ball_count.setValue(int(DEFAULTS["NBall"]))
            self.new_doc.setChecked(bool(DEFAULTS["new_document"]))
            self.update_preview()

        def update_preview(self):
            """Show derived dimensions plus any problem with the current values."""
            p = self.parameters()
            errors, warnings = validate(p)

            lines = ["Bore ø%g  ·  outside ø%g  ·  width %g"
                     % (2 * p["R1"], 2 * p["R4"], p["TH"])]
            if not errors:
                lines.append("Ball pitch radius: %g mm" % ball_pitch_radius(p))
            for message in errors:
                lines.append("Error: " + message)
            for message in warnings:
                lines.append("Warning: " + message)

            self.preview.setText("\n".join(lines))
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(not errors)

        def accept(self):
            p = self.parameters()
            errors, warnings = validate(p)
            if errors:
                QtWidgets.QMessageBox.critical(
                    self, "Ball bearing", "This bearing cannot be built:\n\n- "
                    + "\n- ".join(errors))
                return
            if warnings:
                answer = QtWidgets.QMessageBox.warning(
                    self, "Ball bearing",
                    "This builds, but it is not a working bearing:\n\n- "
                    + "\n- ".join(warnings) + "\n\nCreate it anyway?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No)
                if answer != QtWidgets.QMessageBox.Yes:
                    return
            super(BearingDialog, self).accept()

    # Values carry over to the next run within the same FreeCAD session.
    _last_values = dict(DEFAULTS)

    def show_dialog():
        """Ask for the parameters and build the bearing if the user confirms."""
        global _last_values
        dialog = BearingDialog(_last_values)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        _last_values = dialog.parameters()
        try:
            return build_bearing(_last_values)
        except Exception as exc:  # OCC can still refuse a geometrically odd set
            App.Console.PrintError("Ball bearing: %s\n" % exc)
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(), "Ball bearing",
                "FreeCAD could not build this bearing:\n\n%s" % exc)
            return None


# FreeCAD executes a macro with __name__ set to "__main__"; the extra names
# cover being pasted into the Python console.
if __name__ in ("__main__", "__builtin__", "builtins"):
    if App.GuiUp:
        show_dialog()
    else:
        build_bearing(DEFAULTS)
