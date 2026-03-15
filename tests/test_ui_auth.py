from src.ui import auth


def test_get_auth_service_caches_factory_result(monkeypatch):
    state = {}
    created = []

    monkeypatch.setattr(auth, "get_state", lambda key: state.get(key))
    monkeypatch.setattr(auth, "set_state", lambda key, value: state.__setitem__(key, value))

    def factory():
        instance = object()
        created.append(instance)
        return instance

    first = auth.get_auth_service(factory)
    second = auth.get_auth_service(factory)

    assert first is second
    assert created == [first]


def test_get_auth_service_uses_existing_cached_instance(monkeypatch):
    cached = object()

    monkeypatch.setattr(auth, "get_state", lambda key: cached)
    monkeypatch.setattr(auth, "set_state", lambda key, value: None)

    resolved = auth.get_auth_service(lambda: (_ for _ in ()).throw(AssertionError("factory should not run")))

    assert resolved is cached
