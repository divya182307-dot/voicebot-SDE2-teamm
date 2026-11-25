"""Week 3 module health aggregation."""

from importlib import import_module


MODULES = {
    "audio": (
        "app.gateways.audio_gateway",
        "AudioGateway"
    ),
    "transcription": (
        "app.gateways.transcription_gateway",
        "TranscriptionGateway"
    ),
    "reasoning": (
        "app.gateways.reasoning_gateway",
        "ReasoningGateway"
    ),
    "workflow": (
        "app.gateways.workflow_gateway",
        "WorkflowGateway"
    )
}


def get_module_health():

    modules = {
        "backend": {
            "status": "healthy"
        }
    }

    for name, (module_path, class_name) in MODULES.items():

        try:
            module = import_module(module_path)
            getattr(module, class_name)

            modules[name] = {
                "status": "available"
            }

        except Exception:
            modules[name] = {
                "status": "unavailable"
            }

    all_available = all(
        module["status"] != "unavailable"
        for module in modules.values()
    )

    return {
        "status": (
            "healthy" if all_available else "degraded"
        ),
        "check_type": "import_availability",
        "modules": modules
    }
