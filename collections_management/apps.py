from django.apps import AppConfig


class CollectionsManagementConfig(AppConfig):
    name = 'collections_management'

    def ready(self):
        import collections_management.signals  # noqa: F401
