"""Production portal source wired to fresh local PostgreSQL and Keycloak."""
import os
def create_app():
    os.environ['IQS_REGISTRATION_ROOT']='/runtime/registration'
    import registration_app as r
    from core_api import create_app as api
    return api(r)
