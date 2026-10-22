# Importing drawings into SwiftCut

Open a drawing with **File > Import…** (Cmd+I on macOS, Ctrl+I
elsewhere), by dropping the file on the canvas, or with **Open…** in the
Getting Started guide. The import dialog shows a preview and the options
below; nothing reaches the document until you press **Import**.

## Which file to import

| Format | Extension | What SwiftCut makes of it |
| --- | --- | --- |
| SVG | `.svg` | Vector paths with layers, groups, colors, images, clip paths |
| DXF | `.dxf` | Vector paths, with layers, blocks and colors |
| PDF | `.pdf` | Vector paths, or the page rendered and traced |
| LightBurn | `.lbrn`, `.lbrn2` | Vector paths on layers |
| Ruida | `.rd` | Vector paths on layers (colors) |
| PNG, JPEG, BMP | `.png`, `.jpg`, `.jpeg`, `.bmp` | Traced to vectors |

**SVG is the recommended format** for artwork, especially from
Illustrator. **DXF** is the right choice for CAD outlines from Fusion,
Onshape and the like. The four "Import as" modes below apply to SVG
and DXF; for the other vector formats the dialog offers Single shape and
Individual shapes, as before.

### What an SVG keeps

- Layers: the top-level groups that have an id, the layers of
  Illustrator and Inkscape, when everything at the top of the file is
  such a group. A file with shapes beside its named groups (Illustrator
  writes a one-layer document that way) has no layers: its named groups
  are groups.
- Groups, nested as they are in the file.
- Colors of strokes and fills, including Illustrator's style classes.
- Placed images, embedded or linked, together with their clip paths.
  An image that is rotated, skewed or flipped is not imported; the
  dialog says so.
- Text only when it is outlined. Outline it first (Illustrator:
  **Type > Create Outlines**; Inkscape: **Path > Object to Path**).
  The dialog lists any text that is not outlined.
- Size: a file without physical units is sized by the dialog's **DPI**
  row. Illustrator writes points: set it to **72** for an Illustrator
  file (Inkscape: 96). SwiftCut remembers the last value.

### What a DXF keeps

- Layers.
- Blocks (INSERT) as groups.
- Colors.
- Text, converted to paths.
- No images: a DXF cannot carry a placed picture.

## Import as

The dialog has an **Import as** control with four modes. It starts on
the first one every time; nothing is remembered between files.

1. **By source layers and groups** (the default). Each layer of the
   file becomes one SwiftCut layer (option **Create a SwiftCut layer
   per source layer**, on by default). Each group becomes one piece.
   Loose paths are grouped into pieces. A file without layers goes on
   the active layer, each of its groups a piece.

   A file with one layer and no groups, which is typical of a CAD DXF,
   imports exactly as Pieces would. The dialog then says "No layers or
   groups in this file; grouping by pieces".

2. **Pieces.** Closed outlines become pieces. Everything inside an
   outline, its holes and the artwork in it, travels with it. Loose
   paths are grouped by how close they are to each other.

3. **Individual shapes.** One shape per path, as SwiftCut always did.

4. **Single shape.** The whole file, or each layer, as one shape, as
   SwiftCut always did.

### Options

**Put interior details on their own layer (engrave).** For Pieces and
By source layers and groups. Artwork inside an outline goes to a new
layer named "<file> engrave" with an Engrave step, so the outline cuts
and the artwork engraves. The step takes the engrave recipe for the
active machine that matches the stock material in the document, if one
does, else the default engrave settings. Holes that share the outline's
layer and color stay with the cut.

**Keep images as rasters.** SVG only, on by default, in every mode. A
placed image imports as an image workpiece of its own, cropped to its
clip path, on its source layer; the vector pieces no longer show it.
Check the steps of its layer before you run the job: like any imported
picture, it lands on a layer whose default step is Contour, which cuts
around the picture's box. Move it to a layer with an Engrave step.

### Limits

- Artwork that has the same color and the same layer as its outline is
  treated like holes. Give it another color or put it on another layer
  in Illustrator.
- A traced logo with no outline around it becomes one piece per shape.
  Put the logo in a group and import By source layers and groups, or
  import it as a Single shape.

## SVG or DXF?

Use **DXF** for outlines drawn in CAD: parts, brackets, boxes. They are
plain geometry and one layer is enough.

Use **SVG** for artwork: logos, lettering, drawings with placed
pictures. SVG keeps images as images and groups as groups, so each
group becomes a piece you can move and put on its own layer.

When a DXF looks like traced artwork (more than 100 closed paths, most
of them under 4 mm²), SwiftCut says so in the dialog: "This looks like
traced artwork. Exporting SVG from Illustrator keeps images as images
and engraves better." **Dismiss** hides it; it does not stop the
import.

### Exporting from Illustrator

1. Use **File > Export > Export As > SVG**, and import it at **72**
   DPI.
2. Outline text first (**Type > Create Outlines**).
3. Keep each placed PNG on its own layer or group.

This is also shown in the Getting Started guide (**Help > Getting
Started**).

## Fixing an import by hand

If the import did not split the drawing the way you wanted, undo it and
import again in another mode, or fix it on the canvas:

Right-click a shape on the canvas:

- **Select Inside** selects the shapes whose center lies inside the
  selected outline (a hole does not leave its contents out).
- **Select Similar > By Color**, **By Source Layer** or **By Size**
  selects the shapes that match the one you right-clicked: the same
  color in the file, the same layer of the same file, or a box area
  within 25% of it.
- **Select All on This Layer** selects everything on its layer.
- **Move to Layer** sends the selection to another layer.

To draw a lasso, hold **Option** (Alt) and drag from an empty spot of
the canvas: the shapes whose center lies inside the loop are selected
(Shift adds to the selection). A plain drag draws the selection
rectangle, as before. Shapes on hidden layers are never selected.
