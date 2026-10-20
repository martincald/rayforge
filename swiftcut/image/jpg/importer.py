import logging
import warnings
from gettext import gettext as _
from pathlib import Path
from typing import ClassVar

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import pyvips

from raygeo.geo import Geometry

from ...core.source_asset import SourceAsset
from ...core.vectorization_spec import TraceSpec, VectorizationSpec
from .. import util
from ..base_importer import (
    Importer,
    ImporterFeature,
)
from ..engine import NormalizationEngine
from ..structures import (
    ImportManifest,
    ParsingResult,
    VectorizationResult,
)
from ..tracing import trace_surface
from .renderer import JPG_RENDERER

logger = logging.getLogger(__name__)


class JpgImporter(Importer):
    label = "JPEG files"
    mime_types = ("image/jpeg",)
    extensions = (".jpg", ".jpeg")
    features: ClassVar[set[ImporterFeature]] = {ImporterFeature.BITMAP_TRACING}

    def __init__(self, data: bytes, source_file: Path | None = None):
        super().__init__(data, source_file)
        self._image: pyvips.Image | None = None

    def scan(self) -> ImportManifest:
        """
        Scans the JPEG to extract physical dimensions from its metadata.
        """
        try:
            image = pyvips.Image.jpegload_buffer(
                self.raw_data, access=pyvips.Access.SEQUENTIAL
            )
            size_mm = util.get_physical_size_mm(image)
            return ImportManifest(
                title=self.source_file.name,
                natural_size_mm=size_mm,
                warnings=self._warnings,
                errors=self._errors,
            )
        except pyvips.Error as e:
            logger.warning(
                f"JPEG scan failed for {self.source_file.name}: {e}"
            )
            self.add_error(_("Failed to scan JPEG file: {}").format(e))
            return ImportManifest(
                title=self.source_file.name, errors=self._errors
            )

    def create_source_asset(self, parse_result: ParsingResult) -> SourceAsset:
        """
        Creates a SourceAsset for JPEG import.
        """
        metadata = util.extract_vips_metadata(self._image)
        metadata["image_format"] = "JPEG"
        _, _, w_px, h_px = parse_result.document_bounds
        width_mm = w_px * parse_result.native_unit_to_mm
        height_mm = h_px * parse_result.native_unit_to_mm

        return SourceAsset(
            source_file=self.source_file,
            original_data=self.raw_data,
            renderer=JPG_RENDERER,
            metadata=metadata,
            thumbnail_data=self._render_thumbnail_from_vips(self._image),
            width_px=int(w_px),
            height_px=int(h_px),
            width_mm=width_mm,
            height_mm=height_mm,
        )

    def vectorize(
        self,
        parse_result: ParsingResult,
        spec: VectorizationSpec,
    ) -> VectorizationResult:
        """Phase 3: Generate vector geometry by tracing the bitmap."""
        assert self._image is not None, "parse() must be called first"
        if not isinstance(spec, TraceSpec):
            raise TypeError("JpgImporter only supports TraceSpec")

        normalized_image = util.normalize_to_rgba(self._image)
        if not normalized_image:
            logger.error("Failed to normalize image to RGBA format.")
            self.add_error(_("Failed to process image data."))
            return VectorizationResult(
                geometries_by_layer={}, source_parse_result=parse_result
            )

        surface = util.vips_rgba_to_cairo_surface(normalized_image)
        geometries = trace_surface(surface, spec)
        merged_geo = Geometry()
        for geo in geometries:
            merged_geo.extend(geo)

        return VectorizationResult(
            geometries_by_layer={None: merged_geo},
            source_parse_result=parse_result,
        )

    def parse(self) -> ParsingResult | None:
        """Phase 2: Parse the JPG into a vips image and extract facts."""
        try:
            image = pyvips.Image.jpegload_buffer(
                self.raw_data, access=pyvips.Access.RANDOM
            )
        except pyvips.Error as e:
            logger.exception("pyvips failed to load JPEG buffer")
            self.add_error(_("Image load failed: {}").format(e))
            self._image = None
            return None

        self._image = image
        # VIPS stores resolution as pixels per millimeter in xres.
        return NormalizationEngine.raster_parse_result(
            float(image.width), float(image.height), image.xres
        )
