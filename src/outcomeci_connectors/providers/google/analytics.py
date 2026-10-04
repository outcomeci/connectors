"""Read-only GA4 Data API reporting, scoped to a numeric property ID."""

from ...provider import Grantable, Operation, Provider
from .auth import authentication

SCOPES = ("https://www.googleapis.com/auth/analytics.readonly",)
PROPERTY = {"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"}
NAME = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"^[A-Za-z][A-Za-z0-9_:]*$"}
DATE = {"type": "string", "pattern": r"^(?:\d{4}-\d{2}-\d{2}|today|yesterday|\d+daysAgo)$"}


def names(maximum):
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": NAME},
            "additionalProperties": False,
        },
    }


def report_schema(realtime=False):
    properties = {
        "dimensions": names(4 if realtime else 9),
        "metrics": {**names(10), "minItems": 1},
        # GA uses int64 strings. Bound result size to 10,000 rows per call.
        "limit": {"type": "string", "pattern": r"^(?:[1-9][0-9]{0,3}|10000)$"},
        "returnPropertyQuota": {"type": "boolean"},
    }
    required = ["metrics", "limit"]
    if not realtime:
        properties.update(
            {
                "dateRanges": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "required": ["startDate", "endDate"],
                        "properties": {"startDate": DATE, "endDate": DATE},
                        "additionalProperties": False,
                    },
                },
                "offset": {"type": "string", "pattern": r"^(?:0|[1-9][0-9]{0,15})$"},
                "keepEmptyRows": {"type": "boolean"},
            }
        )
        required.append("dateRanges")
    return {
        "type": "object",
        "required": ["property", "report"],
        "properties": {
            "property": PROPERTY,
            "report": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def report_operation(realtime=False):
    return Operation(
        description=(
            "Read a GA4 realtime report."
            if realtime
            else "Read a GA4 report for explicit date ranges; paginate with offset."
        )
        + " Returns dimension/metric headers, rows, row count, metadata and quota. Maximum 10,000 rows per call; no administration or writes.",
        method="POST",
        path="/v1beta/properties/{{ input.property }}:"
        + ("runRealtimeReport" if realtime else "runReport"),
        input=report_schema(realtime),
        body="{{ input.report }}",
        expose={
            "dimension_headers": "body.dimensionHeaders",
            "metric_headers": "body.metricHeaders",
            "rows": "body.rows",
            "row_count": "body.rowCount",
            "metadata": "body.metadata",
            "quota": "body.propertyQuota",
        },
        grantable={"property": Grantable(field="property")},
    )


PROVIDER = Provider(
    name="google.analytics",
    base_url="https://analyticsdata.googleapis.com",
    auth=authentication(SCOPES),
    max_requests=25,
    operations={
        "report": report_operation(),
        "realtime": report_operation(True),
        "metadata": Operation(
            description="List supported dimensions and metrics, including custom fields, for the granted GA4 property.",
            method="GET",
            path="/v1beta/properties/{{ input.property }}/metadata",
            input={
                "type": "object",
                "required": ["property"],
                "properties": {"property": PROPERTY},
                "additionalProperties": False,
            },
            expose={"dimensions": "body.dimensions", "metrics": "body.metrics"},
            grantable={"property": Grantable(field="property")},
        ),
    },
)
