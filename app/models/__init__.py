# app/models/__init__.py

# Import all models here so that Alembic can see them.
from .associations import *
from .canonical import *
from .legal_one import *
from .process_monitoring import *
from .rules import *
from .task_group import *
from .batch_execution import BatchExecution, BatchExecutionItem
from .classification import ClassificationBatch, ClassificationItem
from .publication_search import PublicationSearch, PublicationRecord
from .publication_batch import PublicationBatchClassification
from .task_template import TaskTemplate
from .office_classification import OfficeClassificationOverride
from .scheduled_automation import ScheduledAutomation, ScheduledAutomationRun
from .publication_capture import OfficePublicationCursor, PublicationFetchAttempt
from .lawsuit_cache import LawsuitCache
from .office_lawsuit_index import OfficeLawsuitIndex, OfficeLawsuitSync
from .publication_treatment import PublicationTreatmentItem, PublicationTreatmentRun
from .prazo_inicial import (
    PrazoInicialBatch,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from .prazo_inicial_task_template import PrazoInicialTaskTemplate
