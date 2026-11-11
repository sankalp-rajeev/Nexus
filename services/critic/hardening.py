"""Deterministic no-op and explicit tool-reference checks; never execute patch text.

References are recognized in JSON/Python literal tool declarations, call syntax,
and explicit prose (call/invoke/tool named, or tool-specific argument clauses).
Free-form prose cannot be soundly parsed as a programming language: the report
records this grammar rather than claiming semantic verification of all text.
"""
import ast
from dataclasses import dataclass, field
import json
import re


def literal(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        try:
            return ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError):
            return None


@dataclass
class HardeningResult:
    no_op: bool = False
    bad_references: list[str] = field(default_factory=list)
    tool_registry_available: bool = False


def inspect_patch(proposal, config):
    current = config.get(proposal.target_component)
    value = proposal.patch_content if isinstance(current, str) else literal(proposal.patch_content)
    no_op = (proposal.target_component in config and type(value) is type(current) and value == current)
    specs = config.get("TOOL_SPECS", [])
    tools = {s["name"]: set(s.get("args", {})) for s in specs
             if isinstance(s, dict) and isinstance(s.get("name"), str)}
    result = HardeningResult(no_op=bool(no_op), tool_registry_available=bool(tools))
    if not tools:
        return result
    bad = set()

    def check(tool, args=()):
        if not isinstance(tool, str):
            return
        if tool not in tools:
            bad.add(f"unknown tool: {tool}")
        else:
            for arg in args:
                if arg not in tools[tool]:
                    bad.add(f"unknown argument: {tool}.{arg}")

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            tool = obj.get("tool_name", obj.get("tool"))
            if tool is None and ("args" in obj or "parameters" in obj or "argument_schema" in obj):
                tool = obj.get("name")
            if isinstance(tool, str):
                args = obj.get("args", obj.get("arguments", {}))
                names = set(args) if isinstance(args, dict) else set()
                for key in ("parameters", "argument_schema"):
                    schema = obj.get(key, {})
                    if isinstance(schema, dict):
                        names.update(schema.get("properties", {}))
                        names.update(schema.get("required", []))
                check(tool, names)
            for val in obj.values():
                walk(val)
        elif isinstance(obj, str):
            prose(obj)

    def prose(text):
        # Call syntax: tool(arg=value). Calls to basic data helpers are not tools.
        helpers = {"hash", "len", "str", "int", "float", "bool", "dict", "list", "set", "tuple",
                   "max", "min", "sum", "sorted", "enumerate", "range", "zip"}
        # A space before a parenthesis is ordinary prose ("error (e.g. 422)").
        # Attribute calls such as json.dumps(...) are helpers, not agent tools.
        known = "|".join(re.escape(t) for t in tools)
        call_pattern = rf"(?<![\w.])((?:(?:{known})\s*|[a-z][a-z0-9_]*))\(([^()\n]*)\)"
        for match in re.finditer(call_pattern, text):
            tool, body = match.groups()
            tool = tool.strip()
            # Bare variable-only calls can be data helpers or dispatchers, not
            # literal tool invocations; explicit call/invoke prose is checked below.
            if tool not in tools and re.fullmatch(r"\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*", body):
                continue
            if tool not in helpers:
                check(tool, re.findall(r"\b([a-z][a-z0-9_]*)\s*=", body))
                if tool in tools:
                    try:
                        call = ast.parse(f"{tool}({body})", mode="eval").body
                    except SyntaxError:
                        continue
                    if len(call.args) > len(tools[tool]):
                        bad.add(f"unknown positional argument: {tool}[{len(tools[tool])}]")
                    if any(kw.arg is None for kw in call.keywords):
                        bad.add(f"unverifiable argument expansion: {tool}")
        for match in re.finditer(
            r"\b(call|invoke|use)\s+(?:the\s+)?(?:tool\s+)?[`\"']?([a-z][a-z0-9_]+)", text, re.I):
            verb, name = match.groups()
            incidental = {"user_id", "session_id"} | set().union(*tools.values())
            explicit = name in tools or verb.casefold() != "use" and "_" in name
            if explicit and not (verb.casefold() == "use" and name in incidental):
                check(name)
        for match in re.finditer(r"\btool\s+(?:named|called)\s+[`\"']?([a-z][a-z0-9_]+)", text, re.I):
            check(match[1])
        for tool in tools:
            escaped = re.escape(tool)
            # Explicit argument binding, not incidental references to user/session metadata.
            patterns = [rf"\b{escaped}\b\s+(?:with|using|requires?|accepts?)\s+[`\"']?([a-z][a-z0-9_]*)",
                        rf"\bpass\s+[`\"']?([a-z][a-z0-9_]*)[`\"']?\s+to\s+{escaped}\b",
                        rf"\b{escaped}\b[^.\n]{{0,60}}\b([a-z][a-z0-9]*_[a-z0-9_]+)\s+(?:argument|parameter)\b"]
            for pattern in patterns:
                for arg in re.findall(pattern, text, re.I):
                    if "_" in arg or arg in tools[tool]:
                        check(tool, [arg])

    parsed = literal(proposal.patch_content)
    if parsed is not None:
        walk(parsed)
    else:
        prose(proposal.patch_content)
        for block in re.findall(r"```(?:json|python)?\s*\n(.*?)```", proposal.patch_content, re.S):
            walk(literal(block))
    result.bad_references = sorted(bad)
    return result
