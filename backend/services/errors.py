"""One error type for every business-rule failure.

The API always answers a failed rule with:
    { "detail": { "rule": "R3", "message": "...", ...extra fields } }
so the frontend can show `detail.message` and, if it wants, highlight `detail.rule`.
"""


class RuleError(Exception):
    def __init__(self, rule: str, message: str, status_code: int = 422, **extra):
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def to_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message, **self.extra}


def violation(rule: str, code: str, message: str, **extra) -> dict:
    """A single broken rule (used when we collect several at once)."""
    return {"rule": rule, "code": code, "message": message, **extra}


def raise_violations(violations: list[dict], status_code: int = 422) -> None:
    """Raise a RuleError built from a list of violations (first one is primary)."""
    if not violations:
        return
    first = violations[0]
    raise RuleError(
        first["rule"],
        first["message"],
        status_code,
        violations=[{"rule": v["rule"], "message": v["message"]} for v in violations],
    )


def not_found(what: str) -> RuleError:
    return RuleError("NOT_FOUND", f"{what} not found.", 404)
