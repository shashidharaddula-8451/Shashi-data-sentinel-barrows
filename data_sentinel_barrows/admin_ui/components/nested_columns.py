# components/nested_columns.py
#
# Shared helpers to explode STRUCT / ARRAY columns into leaf "virtual" columns
# so every nested field can be enrolled, validated and thresholded like a
# primitive column.
#
# Path syntax (stored as column_name in the registries) follows the Unity
# Catalog schema view, where an array's element is called `items`:
#   struct field        ->  touchpoint.id
#   array element       ->  tickets.items
#   array of struct     ->  stores.selected.items.id
#   nested arrays       ->  accounts.items.brands.items.name
# Resolution is schema-aware: `items` is only treated as the array element
# when the current type IS an array, so a real struct field called `items`
# is still a plain field. Legacy paths using `[]` (stores.selected[].id) are
# still accepted and normalised to the `.items` form.
# MAP / VARIANT are not expanded.
# Same rules as agent1 resolve_nested_column() in 01_baseline_computation
# and 02_validation_agent.

import re
import logging

logger = logging.getLogger(__name__)

EXPANDABLE_TYPES = {"STRUCT", "ARRAY"}

_PRIMITIVE_ALIASES = {
    "INTEGER": "INT", "LONG": "BIGINT", "SHORT": "SMALLINT",
    "BYTE": "TINYINT", "REAL": "FLOAT",
}


def _split_top_level(s: str, sep: str = ","):
    parts, depth, buf, in_bt = [], 0, [], False
    for ch in s:
        if ch == "`":
            in_bt = not in_bt
        elif not in_bt:
            if ch in "<(":
                depth += 1
            elif ch in ">)":
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _strip_type_suffix(t: str) -> str:
    m = re.search(r"\s+(NOT\s+NULL|COMMENT)\b", t, flags=re.I)
    return t[:m.start()].strip() if m else t.strip()


def type_base(t: str) -> str:
    return (t or "").strip().split("<")[0].split("(")[0].strip().upper()


def _type_inner(t: str) -> str:
    t = t.strip()
    return t[t.index("<") + 1: t.rindex(">")]


def _struct_fields(t: str):
    out = []
    for f in _split_top_level(_type_inner(t)):
        name, _, ftype = f.partition(":")
        out.append((name.strip().strip("`"), _strip_type_suffix(ftype)))
    return out


def is_expandable(dtype: str) -> bool:
    return type_base(dtype) in EXPANDABLE_TYPES


ARRAY_ELEMENT = "items"


def is_nested_path(name: str) -> bool:
    return "." in (name or "") or "[]" in (name or "")


def normalize_path(path: str) -> str:
    """Legacy 'a[].b' / 'a[]' -> 'a.items.b' / 'a.items'. Idempotent."""
    p = (path or "").replace("[]", f".{ARRAY_ELEMENT}")
    while ".." in p:
        p = p.replace("..", ".")
    return p.strip(".")


def path_root(path: str) -> str:
    return normalize_path(path).split(".")[0]


def _display_type(t: str) -> str:
    """Type as shown in the schema, e.g. 'int', 'string', 'decimal(10,2)'."""
    return _strip_type_suffix(t or "").strip().lower()


def schema_tree(col_name: str, dtype: str, max_depth: int = 6) -> list:
    """
    Depth-first view of everything below a complex column, mirroring the
    Unity Catalog schema browser. Each entry:
      {kind: 'node'|'leaf', path, name, depth, dtype}
    'node' = nested STRUCT/ARRAY (not configurable, shown for lineage);
    'leaf' = primitive field (configurable like a normal column).
    e.g. stores struct<requested:int, selected:array<struct<id:int,...>>>
      leaf stores.requested            int     depth 1
      node stores.selected             array   depth 1
      node stores.selected.items       struct  depth 2
      leaf stores.selected.items.id    int     depth 3
    """
    out = []

    def add(kind, path, name, depth, t):
        out.append({
            "kind" : kind,
            "path" : path,
            "name" : name,
            "depth": depth,
            "dtype": type_base(t).lower() if kind == "node" else _display_type(t),
        })

    def visit(path, name, t, depth):
        if type_base(t) in EXPANDABLE_TYPES and depth <= max_depth:
            add("node", path, name, depth, t)
            walk(path, t, depth)
        else:
            add("leaf", path, name, depth, t)

    def walk(path, t, depth):
        b = type_base(t)
        if b == "STRUCT":
            for fname, ftype in _struct_fields(t):
                visit(f"{path}.{fname}", fname, ftype, depth + 1)
        elif b == "ARRAY":
            visit(f"{path}.{ARRAY_ELEMENT}", ARRAY_ELEMENT,
                  _type_inner(t), depth + 1)

    try:
        walk(col_name, dtype, 0)
    except Exception as e:
        logger.warning(f"schema_tree({col_name}) failed: {e}")
        return []
    return out


def flatten_nested_type(col_name: str, dtype: str, max_depth: int = 6) -> list:
    """Leaf fields of a STRUCT/ARRAY column: [{path, dtype, parent}]."""
    leaves = []
    for e in schema_tree(col_name, dtype, max_depth):
        if e["kind"] == "leaf":
            b = type_base(e["dtype"])
            leaves.append({
                "path"  : e["path"],
                "dtype" : _PRIMITIVE_ALIASES.get(b, b),
                "parent": col_name,
            })
    return leaves


def _parse_type(t: str):
    b = type_base(t)
    if b == "STRUCT":
        return ("struct", {n: _parse_type(ft) for n, ft in _struct_fields(t)})
    if b == "ARRAY":
        return ("array", _parse_type(_type_inner(t)))
    return ("prim", b)


_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def path_plan(path: str, top_dtype: str = None) -> list:
    """
    Turns a registry path into steps: [('col', root), ('field', f) | ('explode', None) ...].
    With top_dtype (the root column's type string) resolution is schema-aware.
    Without it, the segment 'items' is assumed to be an array element.
    Every segment is validated against a strict identifier regex.
    """
    segs = normalize_path(path).split(".")
    for s in segs:
        if not _SEGMENT_RE.match(s):
            raise ValueError(f"Unsafe or empty column path segment: {s!r}")
    plan = [("col", segs[0])]
    node = _parse_type(top_dtype) if top_dtype else None
    for seg in segs[1:]:
        if node is None:
            plan.append(("explode", None) if seg == ARRAY_ELEMENT else ("field", seg))
        elif node[0] == "array" and seg == ARRAY_ELEMENT:
            plan.append(("explode", None))
            node = node[1]
        elif node[0] == "struct" and seg in node[1]:
            plan.append(("field", seg))
            node = node[1][seg]
        else:
            raise ValueError(f"Field {seg!r} not found while resolving {path!r}")
    return plan


def nested_sql_source(safe_fqn: str, path: str, top_dtype: str = None):
    """
    Returns (from_clause, value_expr) for SQL over a registry column path.
    Top-level column -> (fqn, `col`). Each array element step adds
    LATERAL VIEW OUTER explode(...). Pass top_dtype (type of the root column)
    so that a struct field literally named 'items' is not exploded.
    `safe_fqn` must already be validated by the caller.
    """
    if not is_nested_path(path):
        return safe_fqn, "`" + (path or "").replace("`", "``") + "`"
    laterals, expr, n = [], None, 0
    for op, name in path_plan(path, top_dtype):
        if op == "col":
            expr = f"`{name}`"
        elif op == "field":
            expr = f"{expr}.`{name}`"
        else:
            n += 1
            alias = f"_ds_x{n}"
            laterals.append(
                f"LATERAL VIEW OUTER explode({expr}) _ds_t{n} AS {alias}"
            )
            expr = alias
    from_clause = safe_fqn if not laterals else f"{safe_fqn} " + " ".join(laterals)
    return from_clause, expr


def explode_describe_rows(rows: list, name_key: str = "col_name",
                          type_key: str = "data_type") -> list:
    """
    Takes DESCRIBE TABLE rows (list of dicts) and returns a new list where each
    STRUCT/ARRAY column is followed by one row per nested leaf field.
    Adds `field_level` ("Top-level" / "Nested") and `parent_column`.
    """
    out = []
    for r in rows:
        name  = str(r.get(name_key, ""))
        dtype = str(r.get(type_key, "") or "")
        top = dict(r)
        top["field_level"]   = "Top-level"
        top["parent_column"] = ""
        out.append(top)
        if is_expandable(dtype):
            for leaf in flatten_nested_type(name, dtype):
                out.append({
                    name_key        : leaf["path"],
                    type_key        : leaf["dtype"],
                    "comment"       : f"Nested field of {name}",
                    "field_level"   : "Nested",
                    "parent_column" : name,
                })
    return out
