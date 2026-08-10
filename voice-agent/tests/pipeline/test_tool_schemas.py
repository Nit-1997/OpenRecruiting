"""The reader that turns intake-core tool specs into pipecat FunctionSchemas.

This file exists because nothing else in this repo tested it. factory.py read
`t["name"]` and `t["input_schema"]` inline at four sites across two files, and
intake-core is about to change that shape (phase 4). A wrong flip has two
outcomes and BOTH are silent from the outside:

* KeyError inside build_pipeline — the container's /health stays green forever,
  because build_pipeline only runs when a WebRTC peer connects;
* FunctionSchema(properties={}, required=[]) — the model is handed parameterless
  tools and the intake agent quietly stops recording any answer at all.

So the assertions here are deliberately about the VALUES that reach pipecat, not
merely that the call did not raise.

pipecat is stubbed into sys.modules following the pattern in this suite's other
conftests, so FunctionSchema is a MagicMock here and its kwargs are inspected via
call_args. That is enough: what is being tested is this repo's translation, not
pipecat's constructor.
"""
import sys
from unittest.mock import MagicMock

import pytest

for _name in (
    "pipecat",
    "pipecat.adapters",
    "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.function_schema",
):
    sys.modules.setdefault(_name, MagicMock())

from intake_core.screening import ALL_SCREENING_TOOLS  # noqa: E402
from intake_core.tools import INTAKE_TOOLS  # noqa: E402

from src.pipeline.tool_schemas import (  # noqa: E402
    UnsupportedToolSchema,
    function_schemas,
    tool_name,
)


def _kwargs_of(schemas):
    """The kwargs each FunctionSchema was constructed with, in order."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    return [call.kwargs for call in FunctionSchema.call_args_list[-len(schemas):]]


def test_every_intake_tool_yields_a_name():
    assert [tool_name(t) for t in INTAKE_TOOLS] == [
        "update_answer",
        "mark_status",
    ]


def test_every_screening_tool_yields_a_name():
    assert [tool_name(t) for t in ALL_SCREENING_TOOLS] == ["mark_question_covered"]


def test_properties_are_never_empty_for_the_intake_tools():
    """The silent-failure guard. A tool handed to the model with no properties
    cannot be called with arguments, so update_answer would record nothing and
    nothing anywhere would raise."""
    schemas = function_schemas(INTAKE_TOOLS)
    for kwargs in _kwargs_of(schemas):
        assert kwargs["properties"], kwargs["name"]
        assert "qid" in kwargs["properties"], kwargs["name"]
        assert kwargs["required"], kwargs["name"]


def test_properties_are_never_empty_for_the_screening_tool():
    schemas = function_schemas(ALL_SCREENING_TOOLS)
    kwargs = _kwargs_of(schemas)[0]
    assert kwargs["name"] == "mark_question_covered"
    assert "question_id" in kwargs["properties"]
    assert kwargs["required"] == ["question_id"]


def test_an_unrecognised_spec_shape_is_refused_by_name():
    """Not a tolerant reader. A spec this module does not recognise must raise
    where it is read, not degrade into an empty-properties tool downstream."""
    with pytest.raises(UnsupportedToolSchema) as exc:
        function_schemas([{"nonsense": True}])
    assert "nonsense" in str(exc.value) or "tool spec" in str(exc.value)
