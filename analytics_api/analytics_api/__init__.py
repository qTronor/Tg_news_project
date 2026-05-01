__all__ = ["AnalyticsApiService"]


def __getattr__(name: str):
    if name == "AnalyticsApiService":
        from analytics_api.service import AnalyticsApiService

        return AnalyticsApiService
    raise AttributeError(name)
