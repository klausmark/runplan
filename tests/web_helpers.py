from runplan.state.json_repository import new_state
from runplan.web_auth import WebAuthenticator, derive_password_key


class MemoryStateRepository:
    def __init__(self) -> None:
        self.states = {}

    def load(self, program_id: str) -> dict:
        return self.states.setdefault(program_id, new_state(program_id))

    def save(self, program_id: str, state: dict) -> None:
        self.states[program_id] = state

    def delete(self, program_id: str) -> None:
        self.states.pop(program_id, None)


def fake_authenticator(password: str = "secret") -> WebAuthenticator:
    salt = b"0123456789abcdef"
    return WebAuthenticator(
        iterations=1,
        salt=salt,
        proof_key=derive_password_key(password, salt, 1),
        cookie_key=b"c" * 32,
    )
