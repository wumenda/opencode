"""Validation and feature-flag settings."""
from pydantic import BaseModel


class ValidationSettings(BaseModel):
    enable_rule_validator: bool = True
    enable_evidence_analyzer: bool = False
    enable_targeted_critic: bool = False
    enable_output_gate: bool = True
    enable_junction_detector: bool = True
    enable_consistency_checker: bool = True
    inject_image_size: bool = True
    check_port_constraints: bool = True
    reliability_gate_enabled: bool = True
    reliability_threshold: float = 60.0
    reliability_weights_structure: float = 0.40
    reliability_weights_connectivity: float = 0.30
    reliability_weights_semantic: float = 0.20
    reliability_weights_sufficiency: float = 0.10
