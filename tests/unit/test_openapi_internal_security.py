from app.main_api import app


def test_internal_analysis_openapi_declares_bearer_scheme_and_exact_scopes():
    app.openapi_schema = None
    schema = app.openapi()

    scheme = schema["components"]["securitySchemes"]["InternalBearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    accept = schema["paths"]["/internal/v1/crawl-analysis/requests/{request_id}/accept"]["post"]
    assert accept["security"] == [{"InternalBearerAuth": []}]
    assert accept["x-required-scopes"] == ["analysis:accept"]
    report = schema["paths"]["/internal/v1/crawl-analysis/requests/{request_id}/report"]["post"]
    assert report["x-required-scopes"] == ["analysis:submit"]
