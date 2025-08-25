import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_build_method_signature_formats():
    add_src_to_path()
    from analysis.parser import build_method_signature

    sig1 = build_method_signature(
        "com.example", "Hello", "add", [{"type": "int"}, {"type": "int"}], "int"
    )
    assert sig1 == "com.example.Hello#add(int,int):int"

    sig2 = build_method_signature(None, "Hello", "greet", [], "String")
    assert sig2 == "Hello#greet():String"

    sig3 = build_method_signature("org.demo", None, "util", [{"type": "T"}], None)
    assert sig3 == "org.demo.util(T):void"


def test_extract_method_calls_regex():
    add_src_to_path()
    from analysis.calls import extract_method_calls as _extract_method_calls

    code = """
    public class Hello {
        void run() {
            this.doWork();
            super.doMore();
            obj.call(42);
            Helper.staticCall();
            plain();
        }
    }
    """
    calls = _extract_method_calls(code, "Hello")
    names = {c["method_name"] for c in calls}
    assert {"doWork", "doMore", "call", "staticCall", "plain"}.issubset(names)
