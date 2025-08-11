from __future__ import annotations

import sys
from pathlib import Path

import pytest


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

from analysis.code_analysis import build_method_signature  # noqa: E402


@pytest.mark.parametrize(
    "pkg,cls,name,params,ret,expected",
    [
        (
            "a.b",
            "C",
            "m",
            [{"type": "int"}, {"type": "String"}],
            "void",
            "a.b.C#m(int,String):void",
        ),
        (None, "C", "m", [], None, "C#m():void"),
        ("p", None, "f", [{"type": None}], "int", "p.f(?):int"),
        (
            "p.q",
            "Outer.Inner",
            "run",
            [{"type": "List<String>"}],
            None,
            "p.q.Outer.Inner#run(List<String>):void",
        ),
        ("p", "C", "over", [{"type": "int"}], "int", "p.C#over(int):int"),
        ("p", "C", "over", [{"type": "int"}, {"type": "int"}], "int", "p.C#over(int,int):int"),
    ],
)
def test_build_method_signature(pkg, cls, name, params, ret, expected):
    assert build_method_signature(pkg, cls, name, params, ret) == expected
