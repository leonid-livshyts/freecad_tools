# FreeCAD tools

Parametric part generators for FreeCAD, each a single-file macro with a
parameter dialog. Tested on FreeCAD 1.1.3.

## Install

Copy the `.py` file into your FreeCAD macro directory (Macro -> Macros... shows
the path), or point the macro directory at this repository.

## Tools

- **`bearing.py`** - ball bearing: bore, ring radii, thickness, ball count and
  size, optional fillets.
- **`screw.py`** - screw with a modelled ISO metric thread: diameter, length and
  pitch in millimetres, seven head shapes (flat, oval, pan, round, mushroom,
  truss, hex) and four drive recesses (none, slot, Phillips, hex socket).

  `length` is the shank length under the head, except for the countersunk flat
  and oval heads, which sink into the material and so are measured overall.

  Head sizes are derived from the screw diameter as rounded ISO/DIN ratios, so
  any diameter gives a plausible head - right for visualisation and printing,
  not a certified fastener.

  The thread is real helical geometry, built one turn at a time, which costs
  roughly a quarter of a second per turn. The dialog shows the turn count and an
  estimated build time, and warns past 150 turns.

## Without the GUI

Both macros work headless:

```python
import screw
screw.build_screw(dict(screw.DEFAULTS, diameter=6.0, length=20.0, pitch=1.0,
                       head="hex", drive="none"))
```

## Tests

No pytest inside the FreeCAD Flatpak, so the tests are plain scripts that print
a `RESULT:` line. `freecadcmd` always exits 0, so that sentinel is what counts:

```bash
for t in params shank heads drives screw preview; do
  flatpak run --command=freecadcmd org.freecad.FreeCAD tests/test_$t.py 2>&1 | grep -m1 RESULT
done
```

The dialog test needs the GUI binary, because the whole dialog layer sits behind
`App.GuiUp`. It drives the widgets offscreen and mirrors its results to a file,
since the GUI swallows stdout into FreeCAD's Report view:

```bash
flatpak run --env=QT_QPA_PLATFORM=offscreen \
  --env=HARNESS_OUT=$PWD/tests/.dialog_result.txt \
  org.freecad.FreeCAD tests/test_dialog.py >/dev/null 2>&1
grep RESULT tests/.dialog_result.txt
```

Scripts must live inside this directory: the Flatpak sandbox cannot read `/tmp`.
