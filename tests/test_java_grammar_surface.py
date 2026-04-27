"""Java grammar surface tests (B5).

These exercise modern-Java syntax that previously had zero test coverage
in this project: sealed classes, records (deeper than the existing smoke),
pattern-matching switch, switch expressions, text blocks, var inferred
locals, generics with bounds, anonymous inner classes, method-local
classes, varargs methods, default interface methods, parameter annotations,
throws clauses, synchronized methods.

Each test confirms that the parser produces a non-empty extraction with
the expected entries -- not full AST equivalence; that's tree-sitter's
job. The goal is regression coverage so a future grammar bump can't
silently lose extraction of these features.
"""

from __future__ import annotations

from src.analysis.java_treesitter import extract_with_treesitter


def _ext(src: str):
    return extract_with_treesitter(src, "Test.java")


def test_sealed_classes_and_interfaces() -> None:
    src = """
    package demo;
    public sealed interface Shape permits Circle, Square {}
    final class Circle implements Shape {}
    final class Square implements Shape {}
    """
    ext = _ext(src)
    iface_names = {i["name"] for i in ext.interfaces}
    cls_names = {c["name"] for c in ext.classes}
    assert "Shape" in iface_names
    assert "Circle" in cls_names and "Square" in cls_names


def test_records_with_components_and_methods() -> None:
    src = """
    package demo;
    public record Point(int x, int y) {
        public Point {
            if (x < 0) throw new IllegalArgumentException();
        }
        public int sum() { return x + y; }
    }
    """
    ext = _ext(src)
    rec = next((c for c in ext.classes if c["name"] == "Point"), None)
    assert rec is not None and rec.get("kind") == "record"
    method_names = {m["name"] for m in ext.methods}
    assert "sum" in method_names


def test_switch_expression_and_pattern_matching() -> None:
    src = """
    package demo;
    class S {
        String describe(Object o) {
            return switch (o) {
                case Integer i -> "int: " + i;
                case String s when !s.isEmpty() -> "str: " + s;
                default -> "other";
            };
        }
    }
    """
    ext = _ext(src)
    m = next((m for m in ext.methods if m["name"] == "describe"), None)
    assert m is not None
    # Cyclomatic should reflect the switch arms (was: simple methods get 1)
    assert m.get("cyclomatic_complexity", 1) >= 2


def test_text_blocks_and_var() -> None:
    src = '''
    package demo;
    class TB {
        String message() {
            var greeting = """
                hello
                world
                """;
            return greeting;
        }
    }
    '''
    ext = _ext(src)
    assert any(m["name"] == "message" for m in ext.methods)


def test_generics_with_bounds() -> None:
    src = """
    package demo;
    import java.util.Comparator;
    class Box<T extends Comparable<T>> {
        public <R extends Number> R pick(T value) {
            return null;
        }
    }
    """
    ext = _ext(src)
    m = next((m for m in ext.methods if m["name"] == "pick"), None)
    assert m is not None
    # Generic parameter type T is preserved in the parameter record.
    # method_signature isn't built by extract_with_treesitter directly --
    # that happens in extract_file_data; here we verify the parameters.
    params = m.get("parameters") or []
    assert len(params) == 1
    assert params[0].get("type") == "T"
    # Return type with bound (R) is captured (raw text from the AST).
    assert "R" in (m.get("return_type") or "")


def test_anonymous_inner_class_does_not_crash_parser() -> None:
    src = """
    package demo;
    class Anon {
        Runnable r = new Runnable() {
            @Override public void run() {}
        };
    }
    """
    ext = _ext(src)
    # Outer class extracted; the anonymous class isn't a top-level entry but
    # the parser shouldn't crash.
    assert any(c["name"] == "Anon" for c in ext.classes)


def test_method_local_class_does_not_crash_parser() -> None:
    src = """
    package demo;
    class L {
        void run() {
            class Local { int v = 1; }
            Local x = new Local();
        }
    }
    """
    ext = _ext(src)
    assert any(c["name"] == "L" for c in ext.classes)
    assert any(m["name"] == "run" for m in ext.methods)


def test_varargs_method_and_arity() -> None:
    src = """
    package demo;
    class V {
        public String join(String sep, String... parts) { return ""; }
    }
    """
    ext = _ext(src)
    m = next((m for m in ext.methods if m["name"] == "join"), None)
    assert m is not None
    # Arity is 2 (sep + parts). Pre-B2 there was no arity at all.
    assert m.get("arity") == 2
    # Parameter type captured (the spread/varargs marker stays in or is normalized;
    # what matters is the parser identifies two parameters)
    assert len(m.get("parameters") or []) == 2


def test_default_interface_method_modifier() -> None:
    src = """
    package demo;
    interface Greeter {
        default String hello() { return "hi"; }
        String name();
    }
    """
    ext = _ext(src)
    m_default = next((m for m in ext.methods if m["name"] == "hello"), None)
    m_abstract = next((m for m in ext.methods if m["name"] == "name"), None)
    assert m_default is not None and m_default.get("is_default") is True
    # Pure abstract methods don't carry default
    assert m_abstract is not None
    assert m_abstract.get("is_default") is False


def test_throws_and_synchronized() -> None:
    src = """
    package demo;
    import java.io.IOException;
    class T {
        public synchronized void open() throws IOException, InterruptedException {}
    }
    """
    ext = _ext(src)
    m = next((m for m in ext.methods if m["name"] == "open"), None)
    assert m is not None
    assert m.get("is_synchronized") is True
    throws_types = {t["type"] for t in m.get("throws", [])}
    assert {"IOException", "InterruptedException"} <= throws_types


def test_parameter_annotations_dont_crash() -> None:
    src = """
    package demo;
    class P {
        public String fmt(@SuppressWarnings("nullness") String s) { return s; }
    }
    """
    ext = _ext(src)
    m = next((m for m in ext.methods if m["name"] == "fmt"), None)
    assert m is not None
    # Parameter type is still extracted (the annotation doesn't break it)
    params = m.get("parameters") or []
    assert any(p.get("type") == "String" for p in params)


def test_enum_with_methods() -> None:
    src = """
    package demo;
    enum Op {
        PLUS { public int apply(int a, int b) { return a + b; } },
        MINUS { public int apply(int a, int b) { return a - b; } };
        public abstract int apply(int a, int b);
    }
    """
    ext = _ext(src)
    op = next((c for c in ext.classes if c["name"] == "Op"), None)
    assert op is not None and op.get("kind") == "enum"
    # The abstract apply on the enum body should at least be detected.
    apply_methods = [m for m in ext.methods if m["name"] == "apply"]
    assert apply_methods, "expected at least one 'apply' method extracted from enum"
