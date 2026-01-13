# customers/serializers_support.py
from rest_framework import serializers
from django.contrib.auth import get_user_model

from customers.models_support import SupportTicket, SupportTicketMessage, SupportTicketAttachment

User = get_user_model()


class UserLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]


class SupportTicketAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketAttachment
        fields = ["id", "filename", "content_type", "size", "file", "created_at"]

    def get_file(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return None
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class SupportTicketMessageSerializer(serializers.ModelSerializer):
    author = UserLiteSerializer(read_only=True)
    attachments = SupportTicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicketMessage
        fields = ["id", "ticket", "author", "side", "body", "created_at", "attachments"]
        read_only_fields = ["id", "ticket", "author", "side", "created_at", "attachments"]


class SupportTicketSerializer(serializers.ModelSerializer):
    created_by = UserLiteSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "category",
            "priority",
            "status",
            "case_id",
            "created_by",
            "last_activity_at",
            "created_at",
            "updated_at",
            "last_message",
        ]

    def get_last_message(self, obj):
        m = obj.messages.select_related("author").first()
        if not m:
            return None
        return {
            "id": m.id,
            "side": m.side,
            "author_username": m.author.username if m.author else None,
            "created_at": m.created_at,
            "body_preview": (m.body or "")[:160],
        }


class SupportTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    category = serializers.ChoiceField(choices=SupportTicket.Category.choices, required=False)
    priority = serializers.ChoiceField(choices=SupportTicket.Priority.choices, required=False)
    body = serializers.CharField()
    case_id = serializers.IntegerField(required=False, allow_null=True)


class SupportTicketPatchSerializer(serializers.Serializer):
    # client peut seulement clôturer / rouvrir (optionnel)
    status = serializers.ChoiceField(choices=SupportTicket.Status.choices, required=False)
