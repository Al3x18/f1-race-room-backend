"""Define telemetry-domain failures independently from the HTTP API."""


class TelemetryError(RuntimeError):
    """Base class for known telemetry failures."""


class SessionUnavailableError(TelemetryError):
    """The requested session does not exist or has no usable lap data."""


class DriverTelemetryUnavailableError(TelemetryError):
    """The requested driver has no telemetry in the loaded session."""


class TelemetryProviderError(TelemetryError):
    """The upstream telemetry provider could not load the session."""


class TelemetryGenerationError(TelemetryError):
    """The telemetry report could not be rendered."""


class TelemetryArtifactError(TelemetryError):
    """A generated telemetry artifact could not be published or served."""
