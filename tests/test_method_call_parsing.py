#!/usr/bin/env python3

import textwrap

from src.analysis.code_analysis import _determine_call_target, _extract_method_calls


def test_determine_call_target_variants():
    # same class (no qualifier)
    assert _determine_call_target(None, "Calculator") == ("Calculator", "same_class")
    # this qualifier
    assert _determine_call_target("this", "Calculator") == ("Calculator", "this")
    # super qualifier
    assert _determine_call_target("super", "Calculator") == ("super", "super")
    # static class call (capitalized)
    assert _determine_call_target("Math", "Calculator") == ("Math", "static")
    # instance call (lowercase)
    assert _determine_call_target("obj", "Calculator") == ("obj", "instance")


def test_extract_method_calls_common_patterns():
    code = textwrap.dedent(
        """
        public class Calculator {
            public void test() {
                add();                 // same-class
                this.add();             // this
                super.toString();       // super
                Math.max(1, 2);         // static
                handler.process();      // instance
                // noise that should be ignored
                for (int i=0;i<10;i++) {}
                if (x > 0) {}
                new Builder().build();
            }
        }
        """
    )

    calls = _extract_method_calls(code, "Calculator")
    names = {(c["method_name"], c["call_type"]) for c in calls}

    assert ("add", "same_class") in names
    assert ("add", "this") in names
    assert ("toString", "super") in names
    assert ("max", "static") in names
    assert ("process", "instance") in names
