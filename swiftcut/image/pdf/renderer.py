import io
import logging
import warnings
from typing import TYPE_CHECKING, Optional

from ..base_renderer import (
    RasterRenderer,
    RenderSpecification,
    crop_render_spec,
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import pyvips

if TYPE_CHECKING:
    from ...core.source_asset_segment import SourceAssetSegment
    from ...core.workpiece import RenderContext
    from ...image.structures import ImportResult

logger = logging.getLogger(__name__)


class PdfRenderer(RasterRenderer):
    """Renders PDF data."""

    def compute_render_spec(
        self,
        segment: Optional["SourceAssetSegment"],
        target_size: tuple[int, int],
        source_context: "RenderContext",
    ) -> "RenderSpecification":
        return crop_render_spec(
            segment, target_size, source_context, apply_mask=False
        )

    def render_preview_image(
        self,
        import_result: "ImportResult",
        target_width: int,
        target_height: int,
    ) -> pyvips.Image | None:
        """
        Generates a preview image from a PDF import.

        This method has special handling for PDFs. The PdfImporter pre-renders
        the PDF to a PNG and stores it in `base_render_data` as an
        optimization. This method will use that cached PNG if available,
        bypassing the expensive PDF rendering.
        """
        if not import_result.payload:
            return None

        source = import_result.payload.source
        if source.base_render_data:
            try:
                # The importer has cached a pre-rendered PNG. Load it directly.
                image = pyvips.Image.new_from_buffer(
                    source.base_render_data, ""
                )
                # Scale it to the final preview size.
                return image.thumbnail_image(
                    target_width, height=target_height, size="both"
                )
            except pyvips.Error as e:
                logger.warning(
                    f"Failed to load cached preview image from "
                    f"base_render_data: {e}"
                )
                # Fall through to rendering the original PDF.

        # Fallback: If no cached data, render the original PDF from scratch.
        return super().render_preview_image(
            import_result, target_width, target_height
        )

    def _get_page_points(self, data: bytes) -> tuple[float, float] | None:
        # Imported here: pypdf takes about 0.1 s to import.
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            mb = reader.pages[0].mediabox
            w, h = float(mb.width), float(mb.height)
            if w > 0 and h > 0:
                return w, h
        except (PdfReadError, IndexError, AttributeError, ValueError) as e:
            logger.warning(
                "Failed to read PDF page dimensions via pypdf: %s", e
            )

        try:
            probe = pyvips.Image.pdfload_buffer(data, dpi=72)
            w, h = float(probe.width), float(probe.height)
            if w > 0 and h > 0:
                return w, h
        except pyvips.Error as e:
            logger.warning(
                "Failed to read PDF page dimensions via pyvips: %s", e
            )

        return None

    def render_base_image(
        self,
        data: bytes,
        width: int,
        height: int,
        **kwargs,
    ) -> pyvips.Image | None:
        if not data:
            return None

        # Check if data is pre-rendered PNG (from trace import)
        if data[:4] == b"\x89PNG":
            try:
                image = pyvips.Image.new_from_buffer(data, "")
                return image.thumbnail_image(width, height=height, size="both")
            except pyvips.Error as e:
                logger.warning(f"Failed to load PNG data: {e}")
                return None

        # For PDFs, we must determine a DPI to request from the loader
        # to achieve the target pixel dimensions.
        page_pts = self._get_page_points(data)
        if page_pts and width > 0 and height > 0:
            w_pt, h_pt = page_pts
            dpi = max((width / w_pt) * 72.0, (height / h_pt) * 72.0)
        else:
            dpi = 300.0

        try:
            image = pyvips.Image.pdfload_buffer(data, dpi=dpi)
            if not isinstance(image, pyvips.Image) or image.width == 0:
                return None
            return image
        except pyvips.Error:
            logger.warning(
                "Failed to render PDF data to vips image.", exc_info=True
            )
            return None


PDF_RENDERER = PdfRenderer()
