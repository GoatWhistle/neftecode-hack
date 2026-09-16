"""Suite-wide settings.

The agent layer is on by default in the product. The historical suite pins the deterministic mode so its
frozen decisions stay comparable and no test reaches a language model; agent tests in tests/agentic build
their factories and clients explicitly.
"""
import os

os.environ["AGENTIC_DECISION_ENABLED"] = "0"
