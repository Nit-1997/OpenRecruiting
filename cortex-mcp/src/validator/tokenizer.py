"""Cheap Cypher tokenizer for the validator.

We do not parse a full Cypher AST — instead we:
  1) Strip string literals and comments (so they can't trigger false matches)
  2) Locate MATCH / OPTIONAL MATCH clauses
  3) Extract the path-pattern segment of each clause (up to the next clause keyword)
  4) Within those segments only, extract node bindings `(var:Label {props})`

Restricting binding extraction to MATCH segments is critical — otherwise
function calls like `count(c)` and `collect(s.name)` are mis-detected as
unlabeled node bindings.

This is a security-sensitive boundary. The strict rule is:

  - The scanner must err on the side of REJECTING ambiguous input rather
    than letting it through. If we cannot confidently extract a binding's
    label or determine whether `group_id` is filtered on it, the upstream
    validator should reject.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Cypher keywords that end a MATCH path-pattern segment. We stop binding
# extraction when we hit any of these (case-insensitive, word-boundary).
_CLAUSE_TERMINATORS = (
    "WHERE",
    "RETURN",
    "WITH",
    "MATCH",
    "OPTIONAL",
    "UNWIND",
    "UNION",
    "ORDER",
    "SKIP",
    "LIMIT",
    "CALL",
)

_MATCH_KEYWORD_RE = re.compile(
    r"\b(OPTIONAL\s+MATCH|MATCH)\b",
    re.IGNORECASE,
)

_TERMINATOR_RE = re.compile(
    r"\b(" + "|".join(_CLAUSE_TERMINATORS) + r")\b",
    re.IGNORECASE,
)


# A node binding inside a MATCH path pattern:
#   (var:Label)
#   (var:Label {props})
#   (:Label)
#   (:Label {props})
#   (var)
#   ()
_NODE_BINDING_RE = re.compile(
    r"""
    \(
      \s*
      (?P<var>[A-Za-z_][A-Za-z0-9_]*)?       # optional variable name
      \s*
      (?:
        :\s*
        (?P<label>[A-Za-z_][A-Za-z0-9_]*)     # primary label
        (?P<more_labels>(?:\s*:\s*[A-Za-z_][A-Za-z0-9_]*)*)
      )?
      \s*
      (?P<rest>\{[^{}]*\})?                   # optional inline property bag
      \s*
    \)
    """,
    re.VERBOSE,
)


_STRING_LITERAL_RE = re.compile(
    r"""
    '(?:[^'\\]|\\.)*'        # single-quoted (with escapes)
    | "(?:[^"\\]|\\.)*"      # double-quoted
    """,
    re.VERBOSE,
)

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


@dataclass(frozen=True)
class NodeBinding:
    var: str | None
    label: str | None
    extra_labels: tuple[str, ...]
    rest: str   # the inline property bag (between { and }), if any — else ""


def strip_literals_and_comments(query: str) -> str:
    """Blank out string contents and remove comments.

    Outer quote characters are preserved so byte offsets remain meaningful;
    only the contents between them are replaced with spaces.
    """
    out = _BLOCK_COMMENT_RE.sub(lambda m: " " * len(m.group(0)), query)
    out = _LINE_COMMENT_RE.sub(lambda m: " " * len(m.group(0)), out)

    def _blank(m: re.Match[str]) -> str:
        s = m.group(0)
        return s[0] + (" " * (len(s) - 2)) + s[-1]

    out = _STRING_LITERAL_RE.sub(_blank, out)
    return out


def _match_pattern_segments(stripped_query: str) -> list[str]:
    """Return each MATCH/OPTIONAL MATCH clause's path-pattern body.

    Body runs from immediately after the MATCH keyword to the first clause
    terminator at the same (top-level) parenthesis depth.
    """
    segments: list[str] = []
    for m in _MATCH_KEYWORD_RE.finditer(stripped_query):
        start = m.end()
        # Walk forward until we hit a terminator keyword at depth 0.
        depth = 0
        i = start
        end = len(stripped_query)
        while i < end:
            ch = stripped_query[i]
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                depth -= 1
                i += 1
                continue
            if depth == 0:
                # Look for a clause terminator at this position.
                tm = _TERMINATOR_RE.match(stripped_query, i)
                if tm:
                    end = i
                    break
            i += 1
        segments.append(stripped_query[start:end])
    return segments


def extract_node_bindings(stripped_query: str) -> list[NodeBinding]:
    """Extract node bindings only from inside MATCH / OPTIONAL MATCH segments."""
    bindings: list[NodeBinding] = []
    for seg in _match_pattern_segments(stripped_query):
        for m in _NODE_BINDING_RE.finditer(seg):
            var = m.group("var") or None
            label = m.group("label") or None
            more = m.group("more_labels") or ""
            rest = m.group("rest") or ""
            extras = tuple(x.strip() for x in more.split(":") if x.strip())
            bindings.append(NodeBinding(var=var, label=label, extra_labels=extras, rest=rest))
    return bindings


def find_unbounded_variable_paths(stripped_query: str) -> list[str]:
    """Return offending substrings if any variable-length path is unbounded.

    Allowed:  [*1..5]  [*..5]  [r:RELATES_TO*1..3]  [*3]
    Rejected: [*]      [*..]   [*1..]  [r*]   [r:RELATES_TO*]
    """
    findings: list[str] = []
    for m in re.finditer(r"\[[^\]]*\*[^\]]*\]", stripped_query):
        body = m.group(0)
        star_idx = body.index("*")
        after = body[star_idx + 1 : -1].strip()
        if after == "":
            findings.append(body)
            continue
        if ".." not in after:
            if after.isdigit():
                continue
            findings.append(body)
            continue
        lo, hi = after.split("..", 1)
        if hi.strip() == "" or not hi.strip().isdigit():
            findings.append(body)
    return findings
