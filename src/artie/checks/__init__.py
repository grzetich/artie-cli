"""Documentation check registry."""

from artie.checks.auth_clarity import AuthClarityCheck
from artie.checks.base import BaseCheck, CheckResult, Severity
from artie.checks.endpoint_completeness import EndpointCompletenessCheck
from artie.checks.error_documentation import ErrorDocumentationCheck
from artie.checks.example_coverage import ExampleCoverageCheck
from artie.checks.format_efficiency import FormatEfficiencyCheck
from artie.checks.parameter_naming import ParameterNamingCheck
from artie.checks.schema_complexity import SchemaComplexityCheck

# Registry of all available checks, ordered roughly format -> content -> quality.
ALL_CHECKS: list[type[BaseCheck]] = [
    FormatEfficiencyCheck,
    EndpointCompletenessCheck,
    ExampleCoverageCheck,
    ErrorDocumentationCheck,
    AuthClarityCheck,
    ParameterNamingCheck,
    SchemaComplexityCheck,
]

__all__ = ["ALL_CHECKS", "BaseCheck", "CheckResult", "Severity"]
