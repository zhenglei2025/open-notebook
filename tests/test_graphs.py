"""
Unit tests for the open_notebook.graphs module.

This test suite focuses on testing graph structures, tools, and validation
without heavy mocking of the actual processing logic.
"""

from datetime import datetime

import pytest
from content_core.common.exceptions import UnsupportedTypeException

from open_notebook.graphs.prompt import PatternChainState, graph
from open_notebook.graphs.source import (
    _word_extraction_error_message,
    content_process,
)
from open_notebook.graphs.tools import get_current_timestamp
from open_notebook.graphs.transformation import (
    TransformationState,
    run_transformation,
)
from open_notebook.graphs.transformation import (
    graph as transformation_graph,
)

# ============================================================================
# TEST SUITE 1: Graph Tools
# ============================================================================


class TestGraphTools:
    """Test suite for graph tool definitions."""

    def test_get_current_timestamp_format(self):
        """Test timestamp tool returns correct format."""
        timestamp = get_current_timestamp.func()

        assert isinstance(timestamp, str)
        assert len(timestamp) == 14  # YYYYMMDDHHmmss format
        assert timestamp.isdigit()

    def test_get_current_timestamp_validity(self):
        """Test timestamp represents valid datetime."""
        timestamp = get_current_timestamp.func()

        # Parse it back to datetime to verify validity
        year = int(timestamp[0:4])
        month = int(timestamp[4:6])
        day = int(timestamp[6:8])
        hour = int(timestamp[8:10])
        minute = int(timestamp[10:12])
        second = int(timestamp[12:14])

        # Should be valid date components
        assert 2020 <= year <= 2100
        assert 1 <= month <= 12
        assert 1 <= day <= 31
        assert 0 <= hour <= 23
        assert 0 <= minute <= 59
        assert 0 <= second <= 59

        # Should parse as datetime
        dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
        assert isinstance(dt, datetime)

    def test_get_current_timestamp_is_tool(self):
        """Test that function is properly decorated as a tool."""
        # Check it has tool attributes
        assert hasattr(get_current_timestamp, "name")
        assert hasattr(get_current_timestamp, "description")


# ============================================================================
# TEST SUITE 2: Prompt Graph State
# ============================================================================


class TestPromptGraph:
    """Test suite for prompt pattern chain graph."""

    def test_pattern_chain_state_structure(self):
        """Test PatternChainState structure and fields."""
        state = PatternChainState(
            prompt="Test prompt", parser=None, input_text="Test input", output=""
        )

        assert state["prompt"] == "Test prompt"
        assert state["parser"] is None
        assert state["input_text"] == "Test input"
        assert state["output"] == ""

    def test_prompt_graph_compilation(self):
        """Test that prompt graph compiles correctly."""
        assert graph is not None

        # Graph should have the expected structure
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "ainvoke")


# ============================================================================
# TEST SUITE 3: Transformation Graph
# ============================================================================


class TestTransformationGraph:
    """Test suite for transformation graph workflows."""

    def test_transformation_state_structure(self):
        """Test TransformationState structure and fields."""
        from unittest.mock import MagicMock

        from open_notebook.domain.notebook import Source
        from open_notebook.domain.transformation import Transformation

        mock_source = MagicMock(spec=Source)
        mock_transformation = MagicMock(spec=Transformation)

        state = TransformationState(
            input_text="Test text",
            source=mock_source,
            transformation=mock_transformation,
            output="",
        )

        assert state["input_text"] == "Test text"
        assert state["source"] == mock_source
        assert state["transformation"] == mock_transformation
        assert state["output"] == ""

    @pytest.mark.asyncio
    async def test_run_transformation_assertion_no_content(self):
        """Test transformation raises assertion with no content."""
        from unittest.mock import MagicMock

        from open_notebook.domain.transformation import Transformation

        mock_transformation = MagicMock(spec=Transformation)

        state = {
            "input_text": None,
            "transformation": mock_transformation,
            "source": None,
        }

        config = {"configurable": {"model_id": None}}

        with pytest.raises(AssertionError, match="No content to transform"):
            await run_transformation(state, config)

    def test_transformation_graph_compilation(self):
        """Test that transformation graph compiles correctly."""
        assert transformation_graph is not None
        assert hasattr(transformation_graph, "invoke")
        assert hasattr(transformation_graph, "ainvoke")


# ============================================================================
# TEST SUITE 4: Deep Research Context Expansion
# ============================================================================


class TestDeepResearchContextExpansion:
    """Test suite for the Context Expansion feature in Deep Research."""

    def test_context_expansion_result_model(self):
        """Test ContextExpansionResult Pydantic model."""
        from open_notebook.graphs.deep_research import ContextExpansionResult

        # Empty needs
        result = ContextExpansionResult(needs_full_context=[], reason="All chunks sufficient")
        assert result.needs_full_context == []
        assert result.reason == "All chunks sufficient"

        # With source IDs
        result = ContextExpansionResult(
            needs_full_context=["source:abc123", "source:def456"],
            reason="Fragments of a larger process need full context",
        )
        assert len(result.needs_full_context) == 2
        assert "source:abc123" in result.needs_full_context

    def test_context_expansion_result_default_factory(self):
        """Test ContextExpansionResult uses default_factory for needs_full_context."""
        from open_notebook.graphs.deep_research import ContextExpansionResult

        result = ContextExpansionResult(reason="No expansion needed")
        assert result.needs_full_context == []

    def test_max_full_text_length_constant(self):
        """Test MAX_FULL_TEXT_LENGTH is set to 15000."""
        from open_notebook.graphs.deep_research import MAX_FULL_TEXT_LENGTH

        assert MAX_FULL_TEXT_LENGTH == 15_000

    def test_deep_research_graph_compilation(self):
        """Test that the deep research graph compiles correctly after changes."""
        from open_notebook.graphs.deep_research import graph

        assert graph is not None
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "ainvoke")

    def test_deep_research_state_structure(self):
        """Test DeepResearchState has all required fields."""
        from open_notebook.graphs.deep_research import DeepResearchState

        state = DeepResearchState(
            question="Test question",
            notebook_id=None,
            job_id=None,
            research_type="deep",
            outline=None,
            current_section_index=0,
            section_search_count=0,
            section_search_results=[],
            current_queries=[],
            is_material_sufficient=False,
            section_drafts=[],
            section_summaries=[],
            final_report="",
            status="",
            events=[],
        )
        assert state["question"] == "Test question"
        assert state["research_type"] == "deep"

    def test_context_expansion_result_json_serialization(self):
        """Test ContextExpansionResult can serialize to JSON for structured output."""
        from open_notebook.graphs.deep_research import ContextExpansionResult

        result = ContextExpansionResult(
            needs_full_context=["source:abc"],
            reason="Need full process flow",
        )
        json_data = result.model_dump()
        assert json_data["needs_full_context"] == ["source:abc"]
        assert json_data["reason"] == "Need full process flow"

        # Verify it can be parsed back
        parsed = ContextExpansionResult(**json_data)
        assert parsed == result


class TestSourceContentProcess:
    def test_word_extraction_error_message_for_legacy_doc(self):
        message = _word_extraction_error_message("/tmp/example.doc")
        assert "Word 抽取错误" in message
        assert ".docx" in message

    @pytest.mark.asyncio
    async def test_content_process_uses_conversion_fallback_for_legacy_doc(
        self, monkeypatch
    ):
        async def fake_extract_content(_content_state):
            raise UnsupportedTypeException("unsupported legacy doc")

        async def fake_get_content_settings():
            return {}

        def fake_extract_legacy_office_text(_file_path: str):
            return "converted legacy doc text"

        monkeypatch.setattr(
            "open_notebook.graphs.source.extract_content",
            fake_extract_content,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._get_content_settings",
            fake_get_content_settings,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._extract_legacy_office_text",
            fake_extract_legacy_office_text,
        )

        state = {
            "content_state": {"file_path": "/tmp/example.doc"},
            "source_id": "source:test",
            "notebook_ids": [],
            "apply_transformations": [],
            "embed": False,
        }

        result = await content_process(state)
        assert result["content_state"].content == "converted legacy doc text"
        assert result["content_state"].file_path == "/tmp/example.doc"

    @pytest.mark.asyncio
    async def test_content_process_fails_fast_when_legacy_doc_conversion_fails(
        self, monkeypatch
    ):
        async def fake_extract_content(_content_state):
            raise UnsupportedTypeException("unsupported legacy doc")

        async def fake_get_content_settings():
            return {}

        def fake_extract_legacy_office_text(_file_path: str):
            return None

        monkeypatch.setattr(
            "open_notebook.graphs.source.extract_content",
            fake_extract_content,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._get_content_settings",
            fake_get_content_settings,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._extract_legacy_office_text",
            fake_extract_legacy_office_text,
        )

        state = {
            "content_state": {"file_path": "/tmp/example.doc"},
            "source_id": "source:test",
            "notebook_ids": [],
            "apply_transformations": [],
            "embed": False,
        }

        with pytest.raises(ValueError, match="Word 抽取错误"):
            await content_process(state)

    @pytest.mark.asyncio
    async def test_content_process_uses_conversion_fallback_for_wps(
        self, monkeypatch
    ):
        async def fake_extract_content(_content_state):
            raise UnsupportedTypeException("unsupported wps")

        async def fake_get_content_settings():
            return {}

        def fake_extract_legacy_office_text(_file_path: str):
            return "converted wps text"

        monkeypatch.setattr(
            "open_notebook.graphs.source.extract_content",
            fake_extract_content,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._get_content_settings",
            fake_get_content_settings,
        )
        monkeypatch.setattr(
            "open_notebook.graphs.source._extract_legacy_office_text",
            fake_extract_legacy_office_text,
        )

        state = {
            "content_state": {"file_path": "/tmp/example.wps"},
            "source_id": "source:test",
            "notebook_ids": [],
            "apply_transformations": [],
            "embed": False,
        }

        result = await content_process(state)
        assert result["content_state"].content == "converted wps text"
        assert result["content_state"].file_path == "/tmp/example.wps"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
