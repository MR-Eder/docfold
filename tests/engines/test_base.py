"""Tests for the base engine interface and EngineResult dataclass."""

import pytest

from docfold.engines.base import BoundingBox, DocumentEngine, EngineResult, OutputFormat


class TestOutputFormat:
    def test_values(self):
        assert OutputFormat.MARKDOWN == "markdown"
        assert OutputFormat.HTML == "html"
        assert OutputFormat.JSON == "json"
        assert OutputFormat.TEXT == "text"

    def test_from_string(self):
        assert OutputFormat("markdown") == OutputFormat.MARKDOWN
        assert OutputFormat("html") == OutputFormat.HTML


class TestEngineResult:
    def test_minimal_creation(self):
        result = EngineResult(
            content="# Hello",
            format=OutputFormat.MARKDOWN,
            engine_name="test",
        )
        assert result.content == "# Hello"
        assert result.format == OutputFormat.MARKDOWN
        assert result.engine_name == "test"
        assert result.metadata == {}
        assert result.pages is None
        assert result.images is None
        assert result.confidence is None
        assert result.processing_time_ms == 0

    def test_full_creation(self):
        result = EngineResult(
            content="<h1>Hello</h1>",
            format=OutputFormat.HTML,
            engine_name="docling",
            metadata={"pipeline": "standard"},
            pages=5,
            images={"img1.png": "base64data"},
            tables=[{"col1": "val1"}],
            confidence=0.95,
            processing_time_ms=1234,
        )
        assert result.pages == 5
        assert result.confidence == 0.95
        assert "img1.png" in result.images

    def test_docfold_id_is_stable_for_identical_input_and_config(self):
        """Lineage graph relies on ``docfold_id`` being a
        deterministic content-addressed id — re-running the same engine
        with the same config on the same source must produce the same
        id so parent→child edges are idempotent across re-runs."""
        a = EngineResult(
            content="...output bytes may vary between OCR runs...",
            format=OutputFormat.MARKDOWN,
            engine_name="mistral_ocr",
            metadata={"engine_config": {"temperature": 0.0, "model": "mistral-ocr-latest"}},
            source_content_hash="abc123",
        )
        b = EngineResult(
            content="...slightly different output bytes...",
            format=OutputFormat.MARKDOWN,
            engine_name="mistral_ocr",
            metadata={"engine_config": {"temperature": 0.0, "model": "mistral-ocr-latest"}},
            source_content_hash="abc123",
        )
        # Same (source_hash, engine, config) → same id, even though the
        # output bytes differ (deliberately: OCR / LLM engines are
        # non-deterministic at the byte level but stable at the
        # (input, config) level).
        assert a.docfold_id() == b.docfold_id()
        assert a.docfold_id().startswith("CAS_v1:docfold:")

    def test_docfold_id_differs_for_different_engine_or_config(self):
        """Two runs against the same source but with different engines
        (or different configs) must produce distinct ids — otherwise
        swapping engines would silently de-duplicate to the wrong row."""
        base_kwargs = {
            "content": "x",
            "format": OutputFormat.MARKDOWN,
            "source_content_hash": "abc",
        }
        a = EngineResult(
            engine_name="mistral_ocr", metadata={"engine_config": {"k": 1}}, **base_kwargs
        )
        b = EngineResult(engine_name="docling", metadata={"engine_config": {"k": 1}}, **base_kwargs)
        c = EngineResult(
            engine_name="mistral_ocr", metadata={"engine_config": {"k": 2}}, **base_kwargs
        )
        assert a.docfold_id() != b.docfold_id()  # different engine
        assert a.docfold_id() != c.docfold_id()  # different config

    def test_docfold_id_requires_source_content_hash(self):
        """Without an upstream hash, the lineage id has no root — callers
        must provide it (scraping sets ``source_id``, the chunking
        service computes ``source_content_hash``). ``None`` should
        produce ``None``, not crash, so legacy callers keep working."""
        result = EngineResult(
            content="x",
            format=OutputFormat.MARKDOWN,
            engine_name="test",
            source_content_hash=None,
        )
        assert result.docfold_id() is None

    def test_docfold_id_tenant_aware(self):
        """Tenant is in the id pre-image (ADR 0001 security boundary).
        Same content under two tenants must yield distinct ids."""
        from pipeline_common.tenant_context import scoped_tenant

        kwargs = dict(
            content="x",
            format=OutputFormat.MARKDOWN,
            engine_name="t",
            source_content_hash="abc",
            metadata={"engine_config": {}},
        )
        with scoped_tenant("acme"):
            id_acme = EngineResult(**kwargs).docfold_id()
        with scoped_tenant("umbrella"):
            id_umb = EngineResult(**kwargs).docfold_id()
        assert id_acme != id_umb


class TestDocumentEngineInterface:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            DocumentEngine()  # type: ignore

    def test_concrete_implementation(self):
        class DummyEngine(DocumentEngine):
            @property
            def name(self) -> str:
                return "dummy"

            @property
            def supported_extensions(self) -> set[str]:
                return {"txt"}

            async def process(self, file_path, output_format=OutputFormat.MARKDOWN, **kwargs):
                return EngineResult(
                    content="dummy",
                    format=output_format,
                    engine_name=self.name,
                )

            def is_available(self) -> bool:
                return True

        engine = DummyEngine()
        assert engine.name == "dummy"
        assert engine.is_available()
        assert "txt" in engine.supported_extensions
        assert repr(engine) == "<DummyEngine name='dummy' available=True>"


class TestBoundingBox:
    """Tests for the unified BoundingBox dataclass."""

    def test_minimal_creation(self):
        bb = BoundingBox(type="Text", bbox=[10, 20, 100, 50], page=1)
        assert bb.type == "Text"
        assert bb.bbox == [10, 20, 100, 50]
        assert bb.page == 1
        assert bb.text == ""
        assert bb.id == ""
        assert bb.polygon is None
        assert bb.confidence is None
        assert bb.page_width is None
        assert bb.page_height is None

    def test_to_dict_minimal(self):
        bb = BoundingBox(type="Text", bbox=[10, 20, 100, 50], page=1)
        d = bb.to_dict()
        assert d == {
            "type": "Text",
            "bbox": [10, 20, 100, 50],
            "page": 1,
            "page_index": 0,
            "text": "",
            "id": "",
        }
        # Optional fields must be absent (not None) for clean JSON
        assert "polygon" not in d
        assert "confidence" not in d
        assert "page_width" not in d
        assert "page_height" not in d

    def test_to_dict_with_page_dimensions(self):
        """page_width/page_height are critical for frontend normalization."""
        bb = BoundingBox(
            type="Text",
            bbox=[56.7, 72.0, 555.3, 150.0],
            page=1,
            text="Hello",
            id="p1-b0",
            page_width=612.0,
            page_height=792.0,
        )
        d = bb.to_dict()
        assert d["page_width"] == 612.0
        assert d["page_height"] == 792.0
        assert d["bbox"] == [56.7, 72.0, 555.3, 150.0]
        assert d["page"] == 1

    def test_to_dict_with_all_fields(self):
        bb = BoundingBox(
            type="SectionHeader",
            bbox=[50, 100, 550, 200],
            page=2,
            text="Title",
            id="p2-b0",
            polygon=[[50, 100], [550, 100], [550, 200], [50, 200]],
            confidence=0.95,
            page_width=612.0,
            page_height=792.0,
        )
        d = bb.to_dict()
        assert d["type"] == "SectionHeader"
        assert d["page"] == 2
        assert d["page_index"] == 1  # 0-based = page - 1
        assert d["polygon"] == [[50, 100], [550, 100], [550, 200], [50, 200]]
        assert d["confidence"] == 0.95
        assert d["page_width"] == 612.0
        assert d["page_height"] == 792.0

    def test_page_index_is_zero_based(self):
        """page_index must be 0-based for frontend array indexing.

        The frontend's derivePageIndex() checks page_index BEFORE page.
        Without page_index, 1-based page values cause off-by-one:
        page 1 boxes appear on viewer page 2.
        """
        for page_num in [1, 2, 3, 10]:
            bb = BoundingBox(type="Text", bbox=[0, 0, 100, 100], page=page_num)
            d = bb.to_dict()
            assert d["page"] == page_num
            assert d["page_index"] == page_num - 1
            assert d["page_index"] >= 0

    def test_page_dimensions_required_for_normalization(self):
        """Verify that page_width/page_height allow correct 0-1 normalization.

        The frontend divides bbox coords by page dimensions.
        Without them, absolute PDF points (e.g. 612) get clamped to 1.0,
        creating giant overlays.
        """
        bb = BoundingBox(
            type="Text",
            bbox=[56.7, 72.0, 555.3, 750.0],
            page=1,
            page_width=612.0,
            page_height=792.0,
        )
        d = bb.to_dict()
        # Simulate frontend normalization: value / total
        x = d["bbox"][0] / d["page_width"]
        y = d["bbox"][1] / d["page_height"]
        w = (d["bbox"][2] - d["bbox"][0]) / d["page_width"]
        h = (d["bbox"][3] - d["bbox"][1]) / d["page_height"]
        # All normalized values must be in [0, 1]
        assert 0 < x < 1
        assert 0 < y < 1
        assert 0 < w < 1
        assert 0 < h < 1
        # Box must not cover the entire page
        assert w < 0.95
        assert h < 0.95
