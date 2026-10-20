"""Read bounded JUnit XML without trusting contradictory aggregate counters."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

COUNTERS = ("tests", "failures", "errors", "skipped")
MAX_REPORT_BYTES = 16 * 1024 * 1024


def read_test_report(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("JUnit report exceeds 16 MiB limit")
    content = data.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.I):
        raise ValueError("JUnit DTD/entity declarations are unsupported")
    root = ET.fromstring(content)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    classes = set()

    def counts(node):
        if node.tag not in {"testsuite", "testsuites"}:
            raise ValueError("Expected a JUnit testsuite or testsuites root")
        suites = [child for child in node if child.tag in {"testsuite", "testsuites"}]
        cases = node.findall("testcase")
        if suites and cases:
            raise ValueError("Ambiguous JUnit suite mixes nested suites and testcases")
        actual = dict.fromkeys(COUNTERS, 0)
        if suites:
            for suite in suites:
                for key, value in counts(suite).items():
                    actual[key] += value
        else:
            actual["tests"] = len(cases)
            for case in cases:
                classes.add(case.get("classname", ""))
                statuses = [key for key, tag in (("failures", "failure"), ("errors", "error"),
                                                 ("skipped", "skipped")) if case.find(tag) is not None]
                if len(statuses) > 1:
                    raise ValueError("JUnit testcase has conflicting outcomes")
                if statuses:
                    actual[statuses[0]] += 1
        result = {}
        for key in COUNTERS:
            value = node.get(key)
            if value is not None and not re.fullmatch(r"[0-9]+", value):
                raise ValueError(f"Invalid JUnit {key} counter")
            result[key] = int(value) if value is not None else actual[key]
            if (suites or cases) and result[key] != actual[key]:
                raise ValueError(f"JUnit {key} counter contradicts contained results")
        if sum(result[key] for key in ("failures", "errors", "skipped")) > result["tests"]:
            raise ValueError("JUnit outcome counters exceed test count")
        return result

    return counts(root), classes
