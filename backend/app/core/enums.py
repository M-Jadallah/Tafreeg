from enum import StrEnum


class BatchType(StrEnum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    UNKNOWN = "unknown"


class JobStatus(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"
    FETCHING_METADATA = "fetching_metadata"
    QUEUED = "queued"
    CLAIMED = "claimed"
    DOWNLOADING = "downloading"
    TRANSCODING = "transcoding"
    AUDIO_READY = "audio_ready"
    TRANSCRIBING = "transcribing"
    PARSING_RESPONSE = "parsing_response"
    SAVING_TRANSCRIPT = "saving_transcript"
    GENERATING_EXPORTS = "generating_exports"
    COMPLETED = "completed"
    RETRY_WAIT = "retry_wait"
    WAITING_FOR_COOKIES = "waiting_for_cookies"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    DELETING = "deleting"


class WorkerStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELED = "canceled"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ChunkStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"
