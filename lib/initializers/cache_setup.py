from lib.core.cache_store import CacheStore


def initialize_caches(app):
    app.state.cache_store = CacheStore(namespace="rest_server")
    app.state.secret_store = CacheStore(namespace="secrets")
    app.state.session_store = CacheStore(namespace="user_sessions")
    app.state.otp_store = CacheStore(namespace="user_otp")
    app.state.config_store = CacheStore(namespace="app_config")
    app.state.rate_limit_store = CacheStore(namespace="rate_limiting")
    app.state.address_mapping_store = CacheStore(namespace="address_mapping")
    app.state.fitness_sync_store = CacheStore(namespace="fitness_sync")
    app.state.libreview_sync_store = CacheStore(namespace="libreview_sync")
    app.state.ai_conversation_intent_context_store = CacheStore(
        namespace="ai_conversation_intent_context"
    )
