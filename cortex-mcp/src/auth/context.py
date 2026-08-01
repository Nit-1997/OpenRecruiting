from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    org_id: str
    org_name: str
    user_name: str | None
    role: str | None
    scopes: tuple[str, ...]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes
