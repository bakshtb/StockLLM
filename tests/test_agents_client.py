"""
Tests for agents/client.py's _extract_json -- the parser standing between
whatever an LLM actually returns and the rest of the pipeline. Every agent
prompt asks for "ONLY valid JSON", but models drift (markdown fences, stray
commentary), so this is exactly the kind of function that deserves explicit
edge-case coverage rather than only being exercised implicitly by a live
API call.
"""

import json

import pytest

from agents.client import _extract_json


class TestExtractJson:
    def test_clean_json(self):
        result = _extract_json('{"recommendation": "buy", "confidence": 80}')
        assert result == {"recommendation": "buy", "confidence": 80}

    def test_markdown_fenced_json(self):
        text = '```json\n{"recommendation": "hold"}\n```'
        assert _extract_json(text) == {"recommendation": "hold"}

    def test_markdown_fenced_without_json_language_tag(self):
        text = '```\n{"recommendation": "hold"}\n```'
        assert _extract_json(text) == {"recommendation": "hold"}

    def test_stray_text_before_and_after(self):
        text = 'Here is my analysis:\n{"recommendation": "sell"}\nHope that helps!'
        assert _extract_json(text) == {"recommendation": "sell"}

    def test_leading_trailing_whitespace(self):
        text = '   \n  {"recommendation": "hold"}  \n  '
        assert _extract_json(text) == {"recommendation": "hold"}

    def test_nested_objects_and_arrays(self):
        text = '{"key_risks": ["a", "b"], "judge": {"confidence": 50}}'
        assert _extract_json(text) == {"key_risks": ["a", "b"], "judge": {"confidence": 50}}

    def test_malformed_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("this is not json at all")

    def test_truncated_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json('{"recommendation": "buy", "confidence":')
