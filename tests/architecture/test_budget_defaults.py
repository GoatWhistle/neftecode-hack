import inspect

from neftecode.application.agentic.decision import AgenticMakeDecision
from neftecode.application.contracts import DecisionCommand, LiveAdviceCommand, PlanningCommand
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.application.use_cases.planning.builder import PlanBuilderMixin
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET, CandidateGenerator
from neftecode.evaluation.benchmark_run import Benchmark
from neftecode.application.services.tank_estimate import TankEstimateCheck
from neftecode.infrastructure.live.advisor import LiveAdviceAdapter
from neftecode.presentation.demo import Demo
from neftecode.presentation.web.server import DemoService


def default_of(target, parameter: str = "budget"):
    return inspect.signature(target).parameters[parameter].default


def test_every_product_entry_point_uses_the_single_default_budget():
    assert DecisionCommand().budget == DEFAULT_BUDGET
    assert PlanningCommand().budget == DEFAULT_BUDGET
    assert LiveAdviceCommand("2026-01-01", "baseline").budget == DEFAULT_BUDGET
    assert default_of(MakeDecision.decide) == DEFAULT_BUDGET
    assert default_of(MakeDecision.release) == DEFAULT_BUDGET
    assert default_of(AgenticMakeDecision.decide) == DEFAULT_BUDGET
    assert default_of(PlanOperation.plan) == DEFAULT_BUDGET
    assert default_of(PlanBuilderMixin.build_plans) == DEFAULT_BUDGET
    assert default_of(TankEstimateCheck.evaluate) == DEFAULT_BUDGET
    assert CandidateGenerator.__dataclass_fields__["budget"].default == DEFAULT_BUDGET
    assert Benchmark.__dataclass_fields__["budget"].default == DEFAULT_BUDGET
    assert LiveAdviceAdapter.__dataclass_fields__["budget"].default == DEFAULT_BUDGET
    assert Demo.__dataclass_fields__["budget"].default == DEFAULT_BUDGET
    assert DemoService.__dataclass_fields__["budget"].default == DEFAULT_BUDGET
