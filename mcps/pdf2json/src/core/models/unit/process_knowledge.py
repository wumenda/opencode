from dataclasses import dataclass, field


@dataclass
class EquipmentRef:
    tag: str
    name: str | None = None
    equipment_type: str | None = None
    function: str | None = None


@dataclass
class ConnectionRef:
    source_tag: str
    target_tag: str
    medium: str | None = None
    stream_description: str | None = None
    flow_direction: str | None = None


@dataclass
class FlowSequenceRef:
    sequence_id: str
    description: str
    equipment_tags: list[str] = field(default_factory=list)
    sequence_type: str = "main_process"


@dataclass
class ProcessKnowledge:
    equipment_refs: list[EquipmentRef] = field(default_factory=list)
    connection_refs: list[ConnectionRef] = field(default_factory=list)
    flow_sequence_refs: list[FlowSequenceRef] = field(default_factory=list)
    raw_text: str = ""
