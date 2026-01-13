import django_filters
from django.db.models import Q
from django.utils import timezone
from .models import CollectionCase


class CollectionCaseFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="filter_q")
    status = django_filters.CharFilter(field_name="status")
    priority = django_filters.CharFilter(field_name="priority")

    assigned_to = django_filters.NumberFilter(field_name="assigned_to_id")
    portfolio = django_filters.NumberFilter(field_name="portfolio_id")
    debtor = django_filters.NumberFilter(field_name="debtor_id")

    overdue = django_filters.BooleanFilter(method="filter_overdue")

    next_action_date_from = django_filters.DateFilter(field_name="next_action_date", lookup_expr="gte")
    next_action_date_to = django_filters.DateFilter(field_name="next_action_date", lookup_expr="lte")

    class Meta:
        model = CollectionCase
        # IMPORTANT: on ne met pas "portfolio" ni "debtor" ici pour éviter l’auto-resolve
        fields = ["status", "priority"]

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(reference__icontains=value) | Q(notes__icontains=value))

    def filter_overdue(self, queryset, name, value):
        if value is None:
            return queryset
        today = timezone.localdate()
        if value:
            return queryset.filter(next_action_date__lt=today)
        return queryset.exclude(next_action_date__lt=today)
