from django.test import SimpleTestCase

from .services import (
    parse_cobertura_xml,
    parse_lcov,
    parse_coverage_report,
    compute_coverage_delta,
)


COBERTURA_SAMPLE = """<?xml version="1.0" ?>
<coverage version="7.6.1">
  <sources><source>/app</source></sources>
  <packages>
    <package name="app">
      <classes>
        <class name="app.py" filename="app.py" line-rate="0.75" branch-rate="0.5">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="0"/>
            <line number="4" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>"""

LCOV_SAMPLE = """SF:src/index.js
DA:1,1
DA:2,0
DA:3,5
LF:3
LH:2
end_of_record
"""


class CoberturaParserTests(SimpleTestCase):
    def test_parse_cobertura_summary(self):
        summary, files = parse_cobertura_xml(COBERTURA_SAMPLE)

        self.assertEqual(summary['lines_total'], 4)
        self.assertEqual(summary['lines_covered'], 3)
        self.assertEqual(summary['line_coverage'], 75.0)
        self.assertEqual(summary['files_total'], 1)

    def test_parse_cobertura_file_detail(self):
        _, files = parse_cobertura_xml(COBERTURA_SAMPLE)

        self.assertEqual(files[0]['file_path'], 'app.py')
        self.assertEqual(files[0]['line_coverage'], 75.0)
        self.assertEqual(
            files[0]['lines_detail'], {'1': 1, '2': 1, '3': 0, '4': 1}
        )


class LcovParserTests(SimpleTestCase):
    def test_parse_lcov_summary(self):
        summary, files = parse_lcov(LCOV_SAMPLE)

        self.assertEqual(summary['lines_total'], 3)
        self.assertEqual(summary['lines_covered'], 2)
        self.assertEqual(summary['files_total'], 1)

    def test_parse_lcov_file(self):
        _, files = parse_lcov(LCOV_SAMPLE)

        self.assertEqual(files[0]['file_path'], 'src/index.js')
        self.assertEqual(files[0]['line_coverage'], 66.67)
        self.assertEqual(files[0]['lines_detail'], {'1': 1, '2': 0, '3': 5})


class ParseDispatchTests(SimpleTestCase):
    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            parse_coverage_report('<x/>', 'unknown')


class CoverageDeltaTests(SimpleTestCase):
    def test_new_file_delta(self):
        base_files = []
        current_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0, '3': 3}}
        ]

        summary, files = compute_coverage_delta(base_files, current_files)

        self.assertEqual(summary['new_lines_total'], 3)
        self.assertEqual(summary['covered_new_lines'], 2)
        self.assertEqual(summary['delta_coverage'], 66.67)
        self.assertEqual(summary['files_added'], 1)
        self.assertEqual(files[0]['status'], 'added')
        self.assertEqual(files[0]['new_lines'], 3)

    def test_removed_file_delta(self):
        base_files = [
            {'file_path': 'gone.py', 'lines_detail': {'1': 1, '2': 1}}
        ]
        current_files = []

        summary, files = compute_coverage_delta(base_files, current_files)

        self.assertEqual(summary['files_removed'], 1)
        self.assertEqual(files[0]['status'], 'removed')
        self.assertEqual(files[0]['removed_lines'], 2)

    def test_modified_file_only_new_covered_lines_count(self):
        base_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0}}
        ]
        current_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 1, '3': 5, '4': 0}}
        ]

        summary, files = compute_coverage_delta(base_files, current_files)

        self.assertEqual(summary['files_modified'], 1)
        # 新增行：3、4；行 2 从 0 -> 1 也算新增可执行覆盖行
        self.assertEqual(summary['new_lines_total'], 3)
        self.assertEqual(summary['covered_new_lines'], 2)
        self.assertEqual(summary['delta_coverage'], 66.67)
        self.assertEqual(files[0]['new_lines'], 3)

    def test_unchanged_file(self):
        base_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0}}
        ]
        current_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0}}
        ]

        summary, files = compute_coverage_delta(base_files, current_files)

        self.assertEqual(summary['files_unchanged'], 1)
        self.assertEqual(files[0]['status'], 'unchanged')
        self.assertEqual(files[0]['delta_coverage'], 0.0)

    def test_uncovered_line_0_to_0_not_counted_as_new(self):
        # 回归：基线未覆盖(0)、当前仍未覆盖(0) 的行不算新增可执行行
        base_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0}}
        ]
        current_files = [
            {'file_path': 'a.py', 'lines_detail': {'1': 1, '2': 0}}
        ]

        summary, files = compute_coverage_delta(base_files, current_files)

        self.assertEqual(summary['files_unchanged'], 1)
        self.assertEqual(summary['new_lines_total'], 0)
        self.assertEqual(files[0]['status'], 'unchanged')


class CoverageGateConfigTest(SimpleTestCase):
    def test_gate_passes_above_threshold(self):
        from .models import CoverageGateConfig

        config = CoverageGateConfig(enabled=True, min_line_coverage=80.0)
        result = config.evaluate(92.0)
        self.assertTrue(result['passed'])
        self.assertTrue(result['enabled'])
        self.assertEqual(result['threshold'], 80.0)

    def test_gate_fails_below_threshold(self):
        from .models import CoverageGateConfig

        config = CoverageGateConfig(enabled=True, min_line_coverage=80.0)
        result = config.evaluate(65.0)
        self.assertFalse(result['passed'])

    def test_gate_disabled_returns_none(self):
        from .models import CoverageGateConfig

        config = CoverageGateConfig(enabled=False, min_line_coverage=80.0)
        result = config.evaluate(65.0)
        self.assertIsNone(result['passed'])
        self.assertFalse(result['enabled'])
