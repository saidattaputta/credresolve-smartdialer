from app.domain.states import AgentState, CallState

TERMINAL_CALL_STATES = {
    CallState.COMPLETED,
    CallState.FAILED,
    CallState.CANCELLED,
}

ALLOWED_CALL_TRANSITIONS = {
    CallState.QUEUED: {
        CallState.RESERVED,
        CallState.CANCELLED,
    },
    CallState.RESERVED: {
        CallState.INITIATED,
        CallState.QUEUED,
        CallState.CANCELLED,
        CallState.FAILED,
    },
    CallState.INITIATED: {
        CallState.RINGING,
        CallState.ANSWERED,
        CallState.FAILED,
        CallState.CANCELLED,
    },
    CallState.RINGING: {
        CallState.ANSWERED,
        CallState.FAILED,
        CallState.CANCELLED,
    },
    CallState.ANSWERED: {
        CallState.CONNECTED,
        CallState.COMPLETED,
        CallState.FAILED,
    },
    CallState.CONNECTED: {
        CallState.COMPLETED,
        CallState.FAILED,
    },
}

# Terminal states cannot transition to another state.
ALLOWED_CALL_TRANSITIONS.update({
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
})
