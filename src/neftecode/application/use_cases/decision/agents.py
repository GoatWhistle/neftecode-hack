from dataclasses import dataclass


def family(constraint_id: str) -> str:
    return constraint_id.split(".")[0]


@dataclass
class QualityAgent:

    def review(self, evaluation) -> dict:
        checks = [c for c in evaluation.gate.checks if family(c.constraint_id) == "quality"]
        failed = [c for c in checks if c.status == "fail"]
        unknown = [c for c in checks if c.status == "unknown"]
        return {"agent": "quality", "checked": len(checks),
                "passed": len(checks) - len(failed) - len(unknown),
                "vetoes": [c.reason for c in failed],
                "unknown": [c.reason for c in unknown],
                "verdict": "fail" if failed else ("unknown" if unknown else "pass")}


@dataclass
class ReliabilityAgent:

    def review(self, evaluation) -> dict:
        families = ("outflow", "control", "inventory", "additive")
        checks = [c for c in evaluation.gate.checks if family(c.constraint_id) in families]
        failed = [c for c in checks if c.status == "fail"]
        unknown = [c for c in checks if c.status == "unknown"]
        return {"agent": "reliability", "checked": len(checks),
                "passed": len(checks) - len(failed) - len(unknown),
                "vetoes": [c.reason for c in failed],
                "unknown": [c.reason for c in unknown],
                "severity_index": evaluation.severity_index,
                "severity_factors": evaluation.severity_detail,
                "verdict": "fail" if failed else ("unknown" if unknown else "pass"),
                "scope": "Ограничения оборудования заданы сценарием; это не оценка реального ресурса."}
