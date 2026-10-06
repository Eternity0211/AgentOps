"""Infrastructure adapters implementing domain-facing persistence and integrations."""

from .checkpoints import (
    DIAGNOSIS_CHECKPOINT_NAMESPACE,
    ApprovalCheckpointIdentity,
    DiagnosisCheckpointIdentity,
    approval_checkpoint_config,
    diagnosis_checkpoint_config,
    diagnosis_checkpoint_serializer,
    postgres_approval_checkpointer,
    postgres_diagnosis_checkpointer,
)
from .diagnosis_runtime import (
    CheckpointExecutionStatus,
    DiagnosisCheckpointObservation,
    DiagnosisRunOutcome,
    DiagnosisWorkflowRunner,
    checkpoint_observation,
    compiled_diagnosis_runner,
)
from .memory_embeddings import DeterministicIncidentMemoryEmbedder
from .mock_model import (
    MOCK_MODEL_VERSION,
    DeterministicDiagnosisMockModel,
    MockDiagnosisRequest,
    MockModelMalformedOutput,
    MockModelRefusal,
    MockModelResult,
    MockModelScenario,
    MockModelTimeout,
)

__all__ = [
    "DIAGNOSIS_CHECKPOINT_NAMESPACE",
    "MOCK_MODEL_VERSION",
    "ApprovalCheckpointIdentity",
    "CheckpointExecutionStatus",
    "DeterministicDiagnosisMockModel",
    "DeterministicIncidentMemoryEmbedder",
    "DiagnosisCheckpointIdentity",
    "DiagnosisCheckpointObservation",
    "DiagnosisRunOutcome",
    "DiagnosisWorkflowRunner",
    "MockDiagnosisRequest",
    "MockModelMalformedOutput",
    "MockModelRefusal",
    "MockModelResult",
    "MockModelScenario",
    "MockModelTimeout",
    "approval_checkpoint_config",
    "checkpoint_observation",
    "compiled_diagnosis_runner",
    "diagnosis_checkpoint_config",
    "diagnosis_checkpoint_serializer",
    "postgres_approval_checkpointer",
    "postgres_diagnosis_checkpointer",
]
