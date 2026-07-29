from runplan.state.json_repository import new_state


class MemoryStateRepository:
    def __init__(self) -> None:
        self.states = {}

    def load(self, program_id: str) -> dict:
        return self.states.setdefault(program_id, new_state(program_id))

    def save(self, program_id: str, state: dict) -> None:
        self.states[program_id] = state

    def delete(self, program_id: str) -> None:
        self.states.pop(program_id, None)
