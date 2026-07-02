"""Extraction-level tests for the external-call frontier (PR8).

Feeds Java source strings through the tree-sitter extraction and asserts that
static/constructor/instance calls into externally-imported types resolve their
target package via the STRICT resolver (explicit import, single external
wildcard) and never default to the current package. No database required.
"""

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _extract(tmp_path, source: str, rel: str = "com/example/app/A.java"):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    file_path = repo_root / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(source.strip(), encoding="utf-8")
    return extract_file_data(file_path, repo_root)


def _calls_of(result, method_name: str):
    methods = [m for m in result["methods"] if m["name"] == method_name]
    assert methods, f"method {method_name} not extracted"
    return methods[0]["calls"]


def test_static_call_with_explicit_import_resolves_via_explicit_import(tmp_path):
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.fasterxml.jackson.databind.ObjectMapper;
        public class A {
            public void run() { ObjectMapper.findModules(); }
        }
        """,
    )
    calls = _calls_of(result, "run")
    call = next(c for c in calls if c["method_name"] == "findModules")
    assert call["call_type"] == "static"
    assert call["target_class"] == "ObjectMapper"
    assert call["target_package"] == "com.fasterxml.jackson.databind"
    assert call["resolution"] == "explicit_import"
    assert call["receiver_source"] == "static_qualifier"


def test_instance_call_on_local_var_resolves_receiver_via_locals(tmp_path):
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.fasterxml.jackson.databind.ObjectMapper;
        public class A {
            public void run() {
                ObjectMapper m = new ObjectMapper();
                m.readValue("x", Object.class);
            }
        }
        """,
    )
    calls = _calls_of(result, "run")
    call = next(c for c in calls if c["method_name"] == "readValue")
    assert call["call_type"] == "instance"
    assert call["target_class"] == "ObjectMapper"
    assert call["target_package"] == "com.fasterxml.jackson.databind"
    assert call["resolution"] == "explicit_import"
    assert call["receiver_source"] == "local"
    # Constructor call is captured as HIGH-tier material too
    ctor = next(c for c in calls if c["call_type"] == "constructor")
    assert ctor["target_package"] == "com.fasterxml.jackson.databind"
    assert ctor["resolution"] == "explicit_import"
    assert ctor["receiver_source"] == "constructor"


def test_instance_calls_on_field_and_param_resolve_receiver(tmp_path):
    # Field is deliberately declared AFTER the methods that use it, to prove
    # the owner->field-type map is built in a pre-pass (source order agnostic).
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.fasterxml.jackson.databind.ObjectMapper;
        public class A {
            public void useField() { mapper.readTree("x"); }
            public void useParam(ObjectMapper om) { om.writeValueAsString(this); }
            private ObjectMapper mapper;
        }
        """,
    )
    field_call = next(c for c in _calls_of(result, "useField") if c["method_name"] == "readTree")
    assert field_call["target_class"] == "ObjectMapper"
    assert field_call["target_package"] == "com.fasterxml.jackson.databind"
    assert field_call["resolution"] == "explicit_import"
    assert field_call["receiver_source"] == "field"

    param_call = next(
        c for c in _calls_of(result, "useParam") if c["method_name"] == "writeValueAsString"
    )
    assert param_call["target_class"] == "ObjectMapper"
    assert param_call["target_package"] == "com.fasterxml.jackson.databind"
    assert param_call["resolution"] == "explicit_import"
    assert param_call["receiver_source"] == "param"


def test_unimported_type_does_not_default_to_current_package(tmp_path):
    # The strict-resolver trap: the lenient resolver defaults unimported simple
    # types to the current package. Frontier calls must NOT inherit that.
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        public class A {
            public void run() {
                Unimported u = makeIt();
                u.doIt();
                Unimported.staticThing();
            }
        }
        """,
    )
    calls = _calls_of(result, "run")
    instance_call = next(c for c in calls if c["method_name"] == "doIt")
    assert instance_call["receiver_source"] == "local"
    assert instance_call["target_class"] == "Unimported"
    assert instance_call["target_package"] is None
    assert instance_call["resolution"] == "unresolved"

    static_call = next(c for c in calls if c["method_name"] == "staticThing")
    assert static_call["target_package"] is None
    assert static_call["resolution"] == "unresolved"


def test_single_external_wildcard_resolves_low_tier(tmp_path):
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.google.common.collect.*;
        public class A {
            public void run() { Lists.newArrayList(); }
        }
        """,
    )
    call = next(c for c in _calls_of(result, "run") if c["method_name"] == "newArrayList")
    assert call["call_type"] == "static"
    assert call["target_class"] == "Lists"
    assert call["target_package"] == "com.google.common.collect"
    assert call["resolution"] == "wildcard_import"


def test_multiple_external_wildcards_stay_unresolved(tmp_path):
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.google.common.collect.*;
        import org.apache.commons.lang3.*;
        public class A {
            public void run() { Lists.newArrayList(); }
        }
        """,
    )
    call = next(c for c in _calls_of(result, "run") if c["method_name"] == "newArrayList")
    assert call["target_package"] is None
    assert call["resolution"] == "unresolved"


def test_standard_wildcards_do_not_count_as_external_candidates(tmp_path):
    # java.util.* is a "standard" import; the single-external-wildcard rule
    # must still fire for the one genuinely external wildcard.
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import java.util.*;
        import com.google.common.collect.*;
        public class A {
            public void run() { Lists.newArrayList(); }
        }
        """,
    )
    call = next(c for c in _calls_of(result, "run") if c["method_name"] == "newArrayList")
    assert call["target_package"] == "com.google.common.collect"
    assert call["resolution"] == "wildcard_import"


def test_java_util_calls_are_excluded_at_the_writer_layer(tmp_path):
    # JDK receivers resolve at extract time (java.util.List is explicitly
    # imported) but the writer's row collection must drop them: the JDK is not
    # an external dependency and never carries CVE identity.
    add_src_to_path()
    from data.writers.external_calls import _collect_external_call_rows

    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import java.util.List;
        import java.util.ArrayList;
        import com.fasterxml.jackson.databind.ObjectMapper;
        public class A {
            public void run() {
                List<String> xs = new ArrayList<>();
                xs.add("a");
                ObjectMapper m = new ObjectMapper();
                m.readTree("x");
            }
        }
        """,
    )
    rows, stats = _collect_external_call_rows([result])
    import_paths = {r["import_path"] for r in rows}
    method_names = {r["method_name"] for r in rows}
    assert "add" not in method_names, "java.util call leaked into frontier rows"
    assert all(not p.startswith("java.") for p in import_paths)
    # xs.add resolves to java.util (via the List local) and is skipped. The
    # ArrayList constructor is not captured at all: the pre-existing
    # object-creation extraction does not handle diamond/generic types.
    assert stats["jdk_skipped"] == 1
    # The genuinely external calls are still present
    assert "com.fasterxml.jackson.databind.ObjectMapper" in import_paths
    assert {"readTree", "ObjectMapper"}.issubset(method_names)


def test_chained_receivers_stay_invisible(tmp_path):
    # Chained/fluent receivers are documented as invisible in v1: the naive
    # invocation-name split never surfaces the chained callee ("readValue"),
    # so no frontier call may be fabricated for it.
    result = _extract(
        tmp_path,
        """
        package com.example.app;
        import com.fasterxml.jackson.databind.ObjectMapper;
        public class A {
            public void run() {
                ObjectMapper m = new ObjectMapper();
                m.reader().readValue("x");
            }
        }
        """,
    )
    calls = _calls_of(result, "run")
    names = {c["method_name"] for c in calls}
    assert "readValue" not in names
    # The first hop of the chain (m.reader()) IS resolved via the local var.
    first_hop = next(c for c in calls if c["method_name"] == "reader")
    assert first_hop["receiver_source"] == "local"
    assert first_hop["target_package"] == "com.fasterxml.jackson.databind"
