from rest_framework import serializers

from .models import MerchantCategory, Receipt, Transaction


class TransactionSerializer(serializers.ModelSerializer):
    cardType = serializers.CharField(source="card.card_type", read_only=True, default=None)

    class Meta:
        model = Transaction
        fields = ["id", "card", "cardType", "merchant", "amount", "ts", "raw_payload", "created_at"]
        read_only_fields = ["created_at"]


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = ["id", "file_ref", "ocr_text", "matched_tx", "status", "created_at"]
        read_only_fields = ["created_at"]


class MerchantCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantCategory
        fields = "__all__"
